package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"nofx/crypto"
	"os"
	"path/filepath"
	"strings"
	"testing"
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
