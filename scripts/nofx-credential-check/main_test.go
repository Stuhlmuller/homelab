package main

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"nofx/crypto"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestCredentialReportIsMetadataOnlyAndReadOnly(t *testing.T) {
	// Only synthetic key material; never read the operator environment or database.
	privateKey, _, err := crypto.GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	key := bytes.Repeat([]byte{0x11}, 32)
	t.Setenv(crypto.EnvRSAPrivateKey, privateKey)
	t.Setenv(crypto.EnvDataEncryptionKey, base64.StdEncoding.EncodeToString(key))
	service, err := crypto.NewCryptoService()
	if err != nil {
		t.Fatal(err)
	}
	// Direct AES-GCM sealing also supplies synthetic empty and nested envelopes,
	// which EncryptForStorage deliberately skips for ordinary writes.
	seal := func(key []byte, plaintext string) string {
		t.Helper()
		block, err := aes.NewCipher(key)
		if err != nil {
			t.Fatal(err)
		}
		gcm, err := cipher.NewGCM(block)
		if err != nil {
			t.Fatal(err)
		}
		nonce := bytes.Repeat([]byte{0x33}, gcm.NonceSize())
		return "ENC:v1:" + base64.StdEncoding.EncodeToString(nonce) + ":" + base64.StdEncoding.EncodeToString(gcm.Seal(nil, nonce, []byte(plaintext), nil))
	}
	valid, err := service.EncryptForStorage("synthetic-valid-key")
	if err != nil {
		t.Fatal(err)
	}
	wrongKey := seal(bytes.Repeat([]byte{0x22}, 32), "synthetic-wrong-key")
	corrupt := "ENC:v1:invalid:invalid"

	for _, test := range []struct {
		name   string
		fields [3]any
		want   report
	}{
		{"valid", [3]any{valid, valid, valid}, report{Accounts: 1, FieldsPresent: 3, EncryptedFields: 3}},
		{"wrong-key", [3]any{wrongKey, valid, valid}, report{Accounts: 1, FieldsPresent: 3, EncryptedFields: 3, DecryptionFailures: 1}},
		{"corrupt", [3]any{corrupt, valid, valid}, report{Accounts: 1, FieldsPresent: 3, EncryptedFields: 3, DecryptionFailures: 1}},
		{"legacy-valid", [3]any{"synthetic-legacy-key", "synthetic-secret", "synthetic-pass"}, report{Accounts: 1, FieldsPresent: 3}},
		{"legacy", [3]any{" synthetic-legacy-key ", "synthetic-secret", "synthetic-pass"}, report{Accounts: 1, FieldsPresent: 3, WhitespaceAPIKeys: 1}},
		{"blank-nested", [3]any{seal(key, " synthetic-spaced-key "), seal(key, ""), seal(key, valid)}, report{Accounts: 1, FieldsPresent: 3, EncryptedFields: 3, BlankAfterDecryption: 1, NestedEncryptedValues: 1, WhitespaceAPIKeys: 1}},
		{"absent", [3]any{nil, "", nil}, report{Accounts: 1}},
	} {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "fixture.db")
			writer, err := sql.Open("sqlite", path)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := writer.Exec("CREATE TABLE exchanges (exchange_type TEXT, api_key TEXT, secret_key TEXT, passphrase TEXT)"); err != nil {
				t.Fatal(err)
			}
			if _, err := writer.Exec("INSERT INTO exchanges VALUES ('okx', ?, ?, ?)", test.fields[0], test.fields[1], test.fields[2]); err != nil {
				t.Fatal(err)
			}
			if _, err := writer.Exec("INSERT INTO exchanges VALUES ('other', 'excluded-key', 'excluded-secret', 'excluded-pass')"); err != nil {
				t.Fatal(err)
			}
			if err := writer.Close(); err != nil {
				t.Fatal(err)
			}
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			reader, err := sql.Open("sqlite", "file:"+path+"?mode=ro")
			if err != nil {
				t.Fatal(err)
			}
			defer reader.Close()
			var output bytes.Buffer
			if err := writeReport(reader, service, &output); err != nil {
				t.Fatal(err)
			}
			want, err := json.Marshal(test.want)
			if err != nil {
				t.Fatal(err)
			}
			if output.String() != string(want)+"\n" {
				t.Fatalf("metadata mismatch: got %s, want %s", output.String(), want)
			}
			var metadata map[string]int
			if err := json.Unmarshal(output.Bytes(), &metadata); err != nil || len(metadata) != 7 {
				t.Fatal("output must contain exactly seven integer metadata fields")
			}
			if strings.Contains(output.String(), "synthetic") || strings.Contains(output.String(), "ENC:v1:") {
				t.Fatal("output exposed fixture credential material")
			}
			// Account mode shares direct decryption and must skip every unusable row.
			calls := 0
			client := newAccountClient()
			client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				assertAccountRequest(t, r)
				return diagnosticResponse(200, `{"code":"50119","msg":"synthetic-secret","data":[]}`), nil
			})
			output.Reset()
			if err := writeDiagnostic(reader, service, &output, client); err != nil {
				t.Fatal(err)
			}
			var accountResult report
			if err := json.Unmarshal(output.Bytes(), &accountResult); err != nil {
				t.Fatal(err)
			}
			if accountResult.AccountChecks == nil || len(*accountResult.AccountChecks) != 1 {
				t.Fatal("account metadata missing")
			}
			wantCalls := 0
			if test.name == "valid" || test.name == "legacy-valid" {
				wantCalls = 1
			}
			if calls != wantCalls || (*accountResult.AccountChecks)[0].Attempted != (wantCalls == 1) {
				t.Fatal("unusable credentials were sent")
			}
			if strings.Contains(output.String(), "synthetic") || strings.Contains(output.String(), "ENC:v1:") {
				t.Fatal("account diagnostic exposed credentials")
			}
			accountResult.AccountChecks = nil
			if accountResult != test.want {
				t.Fatal("account mode changed storage counters")
			}
			if _, err := reader.Exec("DELETE FROM exchanges"); err == nil {
				t.Fatal("read-only connection unexpectedly accepted a write")
			}
			if err := reader.Close(); err != nil {
				t.Fatal(err)
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("fixture database changed")
			}
		})
	}
}

type diagnosticTransport func(*http.Request) (*http.Response, error)

func (f diagnosticTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func diagnosticResponse(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body))}
}
func assertAccountRequest(t *testing.T, r *http.Request) {
	t.Helper()
	if r.Method != http.MethodGet || r.URL.String() != accountConfigURL || r.Body != nil || r.URL.RawQuery != "" || r.URL.User != nil {
		t.Fatal("diagnostic attempted a request outside its fixed read-only scope")
	}
}

func TestAccountDiagnosticClassifiesWithoutLeaking(t *testing.T) {
	valid := `{"code":"0","data":[{"uid":"123456789","acctLv":"1","feeType":"0","perm":"read_only","autoLoan":false,"enableSpotBorrow":false}]}`
	for _, test := range []struct {
		name, body                         string
		status                             int
		accepted                           bool
		code                               int // -1 means an absent or invalid code.
		jsonValid, envelope, array, fields bool
	}{
		{"valid", valid, 200, true, 0, true, true, true, true},
		{"api-rejected", `{"code":"50119","msg":"synthetic-secret","data":[]}`, 200, false, 50119, true, true, true, true},
		{"http-rejected", `{"code":"50113","msg":"synthetic-secret","data":[]}`, 401, false, 50113, true, true, true, true},
		{"partial", strings.Replace(valid, `"code":"0"`, `"code":"1"`, 1), 200, false, 1, true, true, true, true},
		{"nonnumeric-code", strings.Replace(valid, `"code":"0"`, `"code":"synthetic-secret"`, 1), 200, false, -1, true, true, true, true},
		{"oversized-code", strings.Replace(valid, `"code":"0"`, `"code":"123456789"`, 1), 200, false, -1, true, true, true, true},
		{"non-string-code", `{"code":50119,"data":[]}`, 200, false, -1, true, false, false, false},
		{"non-string-message", strings.Replace(valid, `"code":"0"`, `"code":"0","msg":123`, 1), 200, false, -1, true, false, false, false},
		{"invalid-json", `synthetic-secret`, 200, false, -1, false, false, false, false},
		{"trailing-json", valid + `{}`, 200, false, -1, false, false, false, false},
		{"duplicate-code", strings.Replace(valid, `"code":"0"`, `"code":"0","CODE":"50119"`, 1), 200, false, -1, false, false, false, false},
		{"duplicate-uid", strings.Replace(valid, `"uid":"123456789"`, `"uid":"123456789","\u0075id":"987654321"`, 1), 200, false, -1, false, false, false, false},
		{"null-data", `{"code":"0","data":null}`, 200, false, 0, true, false, false, false},
		{"missing-data", `{"code":"0"}`, 200, false, 0, true, false, false, false},
		{"object-data", `{"code":"0","data":{}}`, 200, false, 0, true, true, false, false},
		{"empty-data", `{"code":"0","data":[]}`, 200, false, 0, true, true, true, true},
		{"invalid-uid", strings.Replace(valid, `"123456789"`, `"synthetic-secret"`, 1), 200, false, 0, true, true, true, true},
		{"empty-level", strings.Replace(valid, `"acctLv":"1"`, `"acctLv":""`, 1), 200, false, 0, true, true, true, true},
		{"typed-level", strings.Replace(valid, `"acctLv":"1"`, `"acctLv":1`, 1), 200, false, 0, true, true, true, false},
		{"typed-borrow", strings.Replace(valid, `"autoLoan":false`, `"autoLoan":"false"`, 1), 200, false, 0, true, true, true, false},
		{"item-rejected", strings.Replace(valid, `"uid":`, `"sCode":"51000","uid":`, 1), 200, false, 0, true, true, true, true},
		{"two-rows", `{"code":"0","data":[{"uid":"123","acctLv":"1"},{"uid":"456","acctLv":"1"}]}`, 200, false, 0, true, true, true, true},
	} {
		t.Run(test.name, func(t *testing.T) {
			calls := 0
			client := newAccountClient()
			client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				assertAccountRequest(t, r)
				if r.Header.Get("OK-ACCESS-KEY") != "synthetic-key" || r.Header.Get("OK-ACCESS-PASSPHRASE") != "synthetic-pass" || r.Header.Get("x-simulated-trading") != "0" {
					t.Fatal("incorrect request authentication shape")
				}
				stamp := r.Header.Get("OK-ACCESS-TIMESTAMP")
				if _, err := time.Parse("2006-01-02T15:04:05.000Z", stamp); err != nil {
					t.Fatal("invalid request timestamp")
				}
				mac := hmac.New(sha256.New, []byte("synthetic-secret"))
				mac.Write([]byte(stamp + "GET/api/v5/account/config"))
				if r.Header.Get("OK-ACCESS-SIGN") != base64.StdEncoding.EncodeToString(mac.Sum(nil)) {
					t.Fatal("incorrect request signature")
				}
				return diagnosticResponse(test.status, test.body), nil
			})
			got := inspectAccount(client, [3]string{"synthetic-key", "synthetic-secret", "synthetic-pass"})
			if calls != 1 || !got.Attempted || got.HTTPStatus != test.status || got.AccountAccepted != test.accepted || got.JSONValid != test.jsonValid || got.EnvelopeValid != test.envelope || got.DataArray != test.array || got.AccountFieldsValid != test.fields {
				t.Fatalf("unexpected metadata: %+v", got)
			}
			if (got.Code == nil) != (test.code == -1) || (got.Code != nil && *got.Code != test.code) {
				t.Fatal("invalid code metadata")
			}
			data, err := json.Marshal(got)
			if err != nil {
				t.Fatal(err)
			}
			for _, forbidden := range []string{"synthetic", "123456789", "987654321", "msg", "secret", "read_only"} {
				if strings.Contains(string(data), forbidden) {
					t.Fatal("response or credential material escaped metadata projection")
				}
			}
			var metadata map[string]any
			if json.Unmarshal(data, &metadata) != nil || len(metadata) != 14 {
				t.Fatal("unexpected output schema")
			}
			for _, value := range metadata {
				switch value.(type) {
				case nil, bool, float64:
				default:
					t.Fatal("output contains non-metadata values")
				}
			}
		})
	}
}

func TestAccountDiagnosticDoesNotRetryOrFollowRedirects(t *testing.T) {
	for _, location := range []string{"https://example.invalid/steal", accountConfigURL + "?unexpected=1", accountConfigURL} {
		client := newAccountClient()
		transport := client.Transport.(*http.Transport)
		if !transport.DisableKeepAlives || transport.Protocols == nil || !transport.Protocols.HTTP1() || transport.Protocols.HTTP2() || transport.Protocols.UnencryptedHTTP2() || transport.Proxy == nil || (transport.TLSClientConfig != nil && transport.TLSClientConfig.InsecureSkipVerify) {
			t.Fatal("unsafe transport configuration")
		}
		calls := 0
		client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
			calls++
			assertAccountRequest(t, r)
			resp := diagnosticResponse(302, `{"code":"0","data":[]}`)
			resp.Header.Set("Location", location)
			return resp, nil
		})
		got := inspectAccount(client, [3]string{"synthetic-key", "synthetic-secret", "synthetic-pass"})
		if calls != 1 || got.HTTPStatus != 302 || got.AccountAccepted {
			t.Fatal("redirect followed or accepted")
		}
	}
	calls := 0
	client := newAccountClient()
	client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		assertAccountRequest(t, r)
		return nil, errors.New("synthetic-key synthetic-secret synthetic-pass")
	})
	got := inspectAccount(client, [3]string{"synthetic-key", "synthetic-secret", "synthetic-pass"})
	data, _ := json.Marshal(got)
	if calls != 1 || got.HTTPStatus != 0 || got.ResponseReadable || got.AccountAccepted || strings.Contains(string(data), "synthetic") {
		t.Fatal("transport failure leaked or retried")
	}
}

type failingDiagnosticBody struct{}

func (failingDiagnosticBody) Read([]byte) (int, error) { return 0, errors.New("synthetic-secret") }
func (failingDiagnosticBody) Close() error             { return nil }
func TestAccountDiagnosticBoundsResponse(t *testing.T) {
	for _, body := range []io.ReadCloser{failingDiagnosticBody{}, io.NopCloser(strings.NewReader(strings.Repeat("x", (8<<20)+1)))} {
		client := newAccountClient()
		client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
			assertAccountRequest(t, r)
			return &http.Response{StatusCode: 200, Body: body}, nil
		})
		got := inspectAccount(client, [3]string{"synthetic-key", "synthetic-secret", "synthetic-pass"})
		if got.HTTPStatus != 200 || got.ResponseReadable || got.JSONValid || got.AccountAccepted {
			t.Fatal("unreadable or oversized response accepted")
		}
	}
}

func TestAccountDiagnosticRejectsInvalidAuthHeaders(t *testing.T) {
	for _, field := range []int{0, 2} {
		for value := 0; value < 256; value++ {
			fields := [3]string{"synthetic-key", "synthetic-secret", "synthetic-pass"}
			fields[field] = "synthetic-before" + string([]byte{byte(value)}) + "synthetic-after"
			valid := (value >= 0x20 || value == '\t') && value != 0x7f
			calls := 0
			client := newAccountClient()
			client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				assertAccountRequest(t, r)
				return nil, errors.New("synthetic-secret")
			})
			got := inspectAccount(client, fields)
			output, _ := json.Marshal(got)
			var metadata map[string]any
			if json.Unmarshal(output, &metadata) != nil {
				t.Fatal("invalid report")
			}
			wantCalls, category := 0, "invalid_auth_header"
			if valid {
				wantCalls, category = 1, "other"
			}
			if calls != wantCalls || got.Attempted != valid || metadata["auth_headers_valid"] != valid || metadata["request_error"] != category || got.HTTPStatus != 0 {
				t.Fatalf("incorrect header-byte classification: field=%d byte=%d", field, value)
			}
			if strings.Contains(string(output), "synthetic") {
				t.Fatal("header value leaked")
			}
		}
	}
	// The signing secret never appears as an HTTP header and must not be checked
	// against the header predicate; its bytes remain valid HMAC input.
	client := newAccountClient()
	calls := 0
	client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		return diagnosticResponse(200, `{"code":"0","data":[]}`), nil
	})
	inspectAccount(client, [3]string{"synthetic-key", "synthetic-secret\x00\r\n", "synthetic-pass"})
	if calls != 1 {
		t.Fatal("HMAC input incorrectly rejected as a header")
	}
}

func TestAccountDiagnosticRequestErrorCategories(t *testing.T) {
	for _, test := range []struct {
		name, category string
		err            error
	}{
		{"dns", "dns", &net.DNSError{Err: "synthetic-secret", Name: "synthetic-host"}},
		{"dns-timeout", "dns", &net.DNSError{Err: "synthetic-secret", IsTimeout: true}},
		{"timeout", "timeout", context.DeadlineExceeded},
		{"certificate", "tls", &tls.CertificateVerificationError{Err: errors.New("synthetic-secret")}},
		{"unknown-authority", "tls", x509.UnknownAuthorityError{}},
		{"hostname", "tls", x509.HostnameError{Certificate: &x509.Certificate{}, Host: "synthetic-host"}},
		{"invalid-certificate", "tls", x509.CertificateInvalidError{Cert: &x509.Certificate{}, Reason: x509.Expired}},
		{"system-roots", "tls", x509.SystemRootsError{Err: errors.New("synthetic-secret")}},
		{"tls-record", "tls", tls.RecordHeaderError{Msg: "synthetic-secret"}},
		{"tls-alert", "tls", tls.AlertError(40)},
		{"eof", "network_io", io.EOF},
		{"unexpected-eof", "network_io", io.ErrUnexpectedEOF},
		{"reset", "network_io", syscall.ECONNRESET},
		{"refused", "network_io", syscall.ECONNREFUSED},
		{"broken-pipe", "network_io", syscall.EPIPE},
		{"network-operation", "network_io", &net.OpError{Op: "read", Net: "tcp", Err: errors.New("synthetic-secret")}},
		{"other", "other", errors.New("synthetic-secret")},
	} {
		t.Run(test.name, func(t *testing.T) {
			client := newAccountClient()
			calls := 0
			client.Transport = diagnosticTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				assertAccountRequest(t, r)
				return nil, &url.Error{Op: "synthetic-secret", URL: "https://synthetic-secret.invalid", Err: test.err}
			})
			got := inspectAccount(client, [3]string{"synthetic-key", "synthetic-secret", "synthetic-pass"})
			output, _ := json.Marshal(got)
			var metadata map[string]any
			if json.Unmarshal(output, &metadata) != nil || metadata["request_error"] != test.category || metadata["auth_headers_valid"] != true || calls != 1 || !got.Attempted || got.HTTPStatus != 0 || got.AccountAccepted {
				t.Fatal("incorrect safe request-error category")
			}
			if strings.Contains(string(output), "synthetic") || strings.Contains(string(output), "https:") {
				t.Fatal("request error or URL leaked")
			}
		})
	}
}
