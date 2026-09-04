package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

type server struct {
	token    string
	kube     *kubeClient
	services []probeConfig
	probes   []probeConfig
}

func (s *server) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})
	protected := func(h http.HandlerFunc) http.HandlerFunc { return s.authenticate(h) }
	mux.HandleFunc("GET /api/v1/status", protected(s.handleStatus))
	mux.HandleFunc("GET /api/v1/host", protected(s.handleHost))
	mux.HandleFunc("GET /api/v1/k8s", protected(s.handleK8s))
	mux.HandleFunc("GET /api/v1/k8s/pods", protected(s.handlePods))
	mux.HandleFunc("GET /api/v1/middlewares", protected(s.handleMiddlewares))
	mux.HandleFunc("GET /api/v1/services", protected(s.handleServices))
	return logging(mux)
}

func (s *server) authenticate(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		const prefix = "Bearer "
		value := r.Header.Get("Authorization")
		if s.token == "" || !strings.HasPrefix(value, prefix) || subtle.ConstantTimeCompare([]byte(strings.TrimSpace(strings.TrimPrefix(value, prefix))), []byte(s.token)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
			return
		}
		next(w, r)
	}
}

func (s *server) handleStatus(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	namespace := requestedNamespace(r)
	ks, ps := s.kube.collect(ctx, namespace)
	data := StatusData{Host: collectHost(ctx), Kubernetes: ks, Pods: ps, Services: runProbes(ctx, s.services), Middlewares: runProbes(ctx, s.probes)}
	writeJSON(w, http.StatusOK, response(r, data))
}
func (s *server) handleHost(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, collectHost(r.Context()))
}
func (s *server) handleK8s(w http.ResponseWriter, r *http.Request) {
	ks, _ := s.kube.collect(r.Context(), requestedNamespace(r))
	writeJSON(w, http.StatusOK, ks)
}
func (s *server) handlePods(w http.ResponseWriter, r *http.Request) {
	_, ps := s.kube.collect(r.Context(), requestedNamespace(r))
	writeJSON(w, http.StatusOK, ps)
}
func (s *server) handleMiddlewares(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, runProbes(r.Context(), s.probes))
}
func (s *server) handleServices(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, runProbes(r.Context(), s.services))
}

func response(r *http.Request, data StatusData) StatusResponse {
	status := Healthy
	for _, st := range []Status{data.Host.Status, data.Kubernetes.Status, data.Pods.Status} {
		if st == Unhealthy {
			status = Unhealthy
		}
		if st == Degraded && status == Healthy {
			status = Degraded
		}
		if st == Unknown && status == Healthy {
			status = Degraded
		}
	}
	for _, m := range data.Middlewares {
		if m.Status == Unhealthy {
			status = Unhealthy
		} else if m.Status == Degraded && status == Healthy {
			status = Degraded
		}
	}
	for _, m := range data.Services {
		if m.Status == Unhealthy {
			status = Unhealthy
		} else if m.Status == Degraded && status == Healthy {
			status = Degraded
		}
	}
	return StatusResponse{SchemaVersion: "v1", RequestID: fmt.Sprintf("%d", time.Now().UnixNano()), Status: status, ObservedAt: time.Now().UTC(), Data: data, Errors: []string{}}
}

func requestedNamespace(r *http.Request) string {
	return strings.TrimSpace(r.URL.Query().Get("namespace"))
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { next.ServeHTTP(w, r) })
}
