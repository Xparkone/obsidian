package main

import (
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	if err := loadConfiguredEnv(); err != nil {
		log.Fatal(err)
	}
	s := &server{token: os.Getenv("STATUS_API_TOKEN"), kube: newKubeClient(), services: loadProbeConfigs("STATUS_SERVICES"), probes: loadProbeConfigs("STATUS_MIDDLEWARES")}
	if s.token == "" {
		log.Println("warning: STATUS_API_TOKEN is empty; protected endpoints will return 401")
	}
	addr := ":" + envOr("STATUS_API_PORT", "8080")
	h := &http.Server{Addr: addr, Handler: s.routes(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second}
	log.Printf("status API listening on http://localhost%s", addr)
	if err := h.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func envOr(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
