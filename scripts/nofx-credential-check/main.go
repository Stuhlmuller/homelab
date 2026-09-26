package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"nofx/crypto"
	"os"
	"strings"

	_ "modernc.org/sqlite"
)

type report struct {
	Accounts              int `json:"accounts"`
	FieldsPresent         int `json:"fields_present"`
	EncryptedFields       int `json:"encrypted_fields"`
	DecryptionFailures    int `json:"decryption_failures"`
	BlankAfterDecryption  int `json:"blank_after_decryption"`
	NestedEncryptedValues int `json:"nested_encrypted_values"`
	WhitespaceAPIKeys     int `json:"whitespace_api_keys"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "credential diagnostic failed")
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) != 1 {
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
	return writeReport(db, service, os.Stdout)
}

func writeReport(db *sql.DB, service *crypto.CryptoService, output io.Writer) error {
	rows, err := db.Query("SELECT api_key, secret_key, passphrase FROM exchanges WHERE exchange_type = 'okx'")
	if err != nil {
		return err
	}
	defer rows.Close()
	var result report
	for rows.Next() {
		var fields [3]sql.NullString
		if err := rows.Scan(&fields[0], &fields[1], &fields[2]); err != nil {
			return err
		}
		result.Accounts++
		for index, field := range fields {
			value := field.String
			if value == "" {
				continue
			}
			result.FieldsPresent++
			if service.IsEncryptedStorageValue(value) {
				result.EncryptedFields++
				value, err = service.DecryptFromStorage(value)
				if err != nil {
					result.DecryptionFailures++
					continue
				}
				if value == "" {
					result.BlankAfterDecryption++
				}
				if service.IsEncryptedStorageValue(value) {
					result.NestedEncryptedValues++
				}
			}
			if index == 0 && value != strings.TrimSpace(value) {
				result.WhitespaceAPIKeys++
			}
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}
	return json.NewEncoder(output).Encode(result)
}
