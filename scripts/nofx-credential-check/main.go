package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"nofx/crypto"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"

	_ "modernc.org/sqlite"
)

type report struct {
	Accounts              int             `json:"accounts"`
	FieldsPresent         int             `json:"fields_present"`
	EncryptedFields       int             `json:"encrypted_fields"`
	DecryptionFailures    int             `json:"decryption_failures"`
	BlankAfterDecryption  int             `json:"blank_after_decryption"`
	NestedEncryptedValues int             `json:"nested_encrypted_values"`
	WhitespaceAPIKeys     int             `json:"whitespace_api_keys"`
	AccountChecks         *[]accountCheck `json:"account_checks,omitempty"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "credential diagnostic failed")
		os.Exit(1)
	}
}

func run() error {
	accountMode := len(os.Args) == 2 && os.Args[1] == "inspect-account"
	if len(os.Args) != 1 && !accountMode {
		return fmt.Errorf("arguments are unsupported")
	}
	service, err := crypto.NewCryptoService()
	if err != nil {
		return err
	}
	db, err := sql.Open("sqlite", "file:/app/data/data.db?mode=ro")
	if err != nil {
		return err
	}
	defer db.Close()
	if accountMode {
		return writeDiagnostic(db, service, os.Stdout, newAccountClient())
	}
	return writeReport(db, service, os.Stdout)
}

func writeReport(db *sql.DB, service *crypto.CryptoService, output io.Writer) error {
	return writeDiagnostic(db, service, output, nil)
}

func writeDiagnostic(db *sql.DB, service *crypto.CryptoService, output io.Writer, client *http.Client) error {
	rows, err := db.Query("SELECT api_key, secret_key, passphrase FROM exchanges WHERE exchange_type = 'okx'")
	if err != nil {
		return err
	}
	defer rows.Close()
	var result report
	if client != nil {
		checks := []accountCheck{}
		result.AccountChecks = &checks
	}
	for rows.Next() {
		var fields [3]sql.NullString
		if err := rows.Scan(&fields[0], &fields[1], &fields[2]); err != nil {
			return err
		}
		result.Accounts++
		var credentials [3]string
		valid := true
		for index, field := range fields {
			value := field.String
			if value == "" {
				valid = false
				continue
			}
			result.FieldsPresent++
			if service.IsEncryptedStorageValue(value) {
				result.EncryptedFields++
				value, err = service.DecryptFromStorage(value)
				if err != nil {
					result.DecryptionFailures++
					valid = false
					continue
				}
				if value == "" {
					result.BlankAfterDecryption++
				}
				if service.IsEncryptedStorageValue(value) {
					result.NestedEncryptedValues++
				}
			}
			if strings.TrimSpace(value) == "" || service.IsEncryptedStorageValue(value) || (index == 0 && value != strings.TrimSpace(value)) {
				valid = false
			}
			credentials[index] = value
			if index == 0 && value != strings.TrimSpace(value) {
				result.WhitespaceAPIKeys++
			}
		}
		if client != nil {
			check := accountCheck{}
			if valid {
				check = inspectAccount(client, credentials)
			}
			*result.AccountChecks = append(*result.AccountChecks, check)
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}
	return json.NewEncoder(output).Encode(result)
}

const accountConfigURL = "https://us.okx.com/api/v5/account/config"

// Output is an allowlist of metadata; never encode a request, response, or error.
type accountCheck struct {
	Attempted          bool `json:"attempted"`
	HTTPStatus         int  `json:"http_status"`
	ResponseReadable   bool `json:"response_readable"`
	JSONValid          bool `json:"json_valid"`
	EnvelopeValid      bool `json:"envelope_valid"`
	Code               *int `json:"code"`
	DataArray          bool `json:"data_array"`
	ItemStatusesValid  bool `json:"item_statuses_valid"`
	AccountRows        int  `json:"account_rows"`
	AccountFieldsValid bool `json:"account_fields_valid"`
	UIDValid           bool `json:"uid_valid"`
	AccountLevelValid  bool `json:"account_level_valid"`
	AccountAccepted    bool `json:"account_accepted"`
}

func newAccountClient() *http.Client {
	// Preserve the application's default proxy/TLS/dial settings. Fresh, single-use
	// HTTP/1 connections avoid retries on reused connections or HTTP/2 streams.
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.DisableKeepAlives = true
	transport.Protocols = new(http.Protocols)
	transport.Protocols.SetHTTP1(true)
	return &http.Client{Transport: transport, Timeout: 30 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}

var numericCode = regexp.MustCompile(`^(0|[1-9][0-9]{0,5})$`)
var accountUID = regexp.MustCompile(`^[0-9]{1,40}$`)

func inspectAccount(client *http.Client, fields [3]string) accountCheck {
	result := accountCheck{Attempted: true}
	timestamp := time.Now().UTC().Format("2006-01-02T15:04:05.000Z")
	mac := hmac.New(sha256.New, []byte(fields[1]))
	mac.Write([]byte(timestamp + "GET/api/v5/account/config"))
	req, err := http.NewRequest(http.MethodGet, accountConfigURL, nil)
	if err != nil {
		return result
	}
	req.Header.Set("OK-ACCESS-KEY", fields[0])
	req.Header.Set("OK-ACCESS-SIGN", base64.StdEncoding.EncodeToString(mac.Sum(nil)))
	req.Header.Set("OK-ACCESS-TIMESTAMP", timestamp)
	req.Header.Set("OK-ACCESS-PASSPHRASE", fields[2])
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-simulated-trading", "0")
	resp, err := client.Do(req)
	if err != nil {
		return result
	}
	defer resp.Body.Close()
	result.HTTPStatus = resp.StatusCode
	body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20+1))
	if err != nil || len(body) > 8<<20 {
		return result
	}
	result.ResponseReadable = true
	// Match the deployed cash-spot transport and Account() decoder, including
	// duplicate-key refusal, typed optional fields, and its UID/acctLv checks.
	if diagnosticValidateJSON(body) != nil {
		return result
	}
	result.JSONValid = true
	var envelope struct {
		Code string          `json:"code"`
		Msg  string          `json:"msg"`
		Data json.RawMessage `json:"data"`
	}
	if json.Unmarshal(body, &envelope) != nil {
		return result
	}
	if numericCode.MatchString(envelope.Code) {
		code, _ := strconv.Atoi(envelope.Code)
		result.Code = &code
	}
	if len(envelope.Data) == 0 || bytes.Equal(envelope.Data, []byte("null")) {
		return result
	}
	result.EnvelopeValid = true
	var items []json.RawMessage
	if json.Unmarshal(envelope.Data, &items) != nil {
		return result
	}
	result.DataArray, result.ItemStatusesValid, result.AccountRows = true, true, len(items)
	for _, item := range items {
		var status struct {
			Code *string `json:"sCode"`
		}
		if len(item) > 0 && item[0] == '{' && (json.Unmarshal(item, &status) != nil || (status.Code != nil && *status.Code != "0")) {
			result.ItemStatusesValid = false
		}
	}
	var accounts []struct {
		UID              string `json:"uid"`
		AccountLevel     string `json:"acctLv"`
		FeeType          string `json:"feeType"`
		Permissions      string `json:"perm"`
		AutoLoan         *bool  `json:"autoLoan"`
		EnableSpotBorrow *bool  `json:"enableSpotBorrow"`
	}
	if json.Unmarshal(envelope.Data, &accounts) != nil {
		return result
	}
	result.AccountFieldsValid = true
	if len(accounts) == 1 {
		result.UIDValid = accountUID.MatchString(accounts[0].UID)
		result.AccountLevelValid = accounts[0].AccountLevel != ""
	}
	result.AccountAccepted = result.HTTPStatus == http.StatusOK && envelope.Code == "0" && result.ItemStatusesValid && result.UIDValid && result.AccountLevelValid
	return result
}

func diagnosticValidateJSON(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	invalid := errors.New("invalid response JSON")
	var value func(int) error
	value = func(depth int) error {
		if depth > 32 {
			return invalid
		}
		token, err := decoder.Token()
		if err != nil {
			return invalid
		}
		delim, container := token.(json.Delim)
		if !container {
			return nil
		}
		closing := json.Delim(']')
		switch delim {
		case '{':
			closing = '}'
			seen := map[string]bool{}
			for decoder.More() {
				token, err := decoder.Token()
				key, ok := token.(string)
				if err != nil || !ok {
					return invalid
				}
				folded := strings.Map(func(r rune) rune {
					minimum := r
					for next := unicode.SimpleFold(r); next != r; next = unicode.SimpleFold(next) {
						if next < minimum {
							minimum = next
						}
					}
					return minimum
				}, key)
				if seen[folded] {
					return invalid
				}
				seen[folded] = true
				if err := value(depth + 1); err != nil {
					return err
				}
			}
		case '[':
			for decoder.More() {
				if err := value(depth + 1); err != nil {
					return err
				}
			}
		default:
			return invalid
		}
		if token, err := decoder.Token(); err != nil || token != closing {
			return invalid
		}
		return nil
	}
	if err := value(0); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return invalid
	}
	return nil
}
