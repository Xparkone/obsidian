package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// loadEnvFile loads simple KEY=VALUE entries. Existing process environment
// variables win over values from the file.
func loadEnvFile(path string, optional bool) error {
	file, err := os.Open(path)
	if err != nil {
		if optional && os.IsNotExist(err) {
			return nil
		}
		return err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	line := 0
	for scanner.Scan() {
		line++
		value := strings.TrimSpace(scanner.Text())
		if value == "" || strings.HasPrefix(value, "#") {
			continue
		}
		value = strings.TrimPrefix(value, "export ")
		parts := strings.SplitN(value, "=", 2)
		if len(parts) != 2 || strings.TrimSpace(parts[0]) == "" {
			return fmt.Errorf("invalid env file %s line %d", path, line)
		}
		key := strings.TrimSpace(parts[0])
		fileValue := strings.TrimSpace(parts[1])
		if len(fileValue) >= 2 && ((fileValue[0] == '\'' && fileValue[len(fileValue)-1] == '\'') || (fileValue[0] == '"' && fileValue[len(fileValue)-1] == '"')) {
			fileValue = fileValue[1 : len(fileValue)-1]
		}
		if _, exists := os.LookupEnv(key); !exists {
			if err := os.Setenv(key, fileValue); err != nil {
				return err
			}
		}
	}
	return scanner.Err()
}

func loadConfiguredEnv() error {
	if path := os.Getenv("STATUS_API_ENV_FILE"); path != "" {
		return loadEnvFile(path, false)
	}
	return loadEnvFile(".env", true)
}
