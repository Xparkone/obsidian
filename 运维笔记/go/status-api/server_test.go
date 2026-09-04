package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func testServer() *server {
	return &server{token: "test-token", kube: &kubeClient{baseURL: "http://127.0.0.1:1", client: http.DefaultClient}}
}

func TestPodAPIPath(t *testing.T) {
	if got := podAPIPath(""); got != "/api/v1/pods" {
		t.Fatalf("all namespaces path = %q", got)
	}
	if got := podAPIPath("production"); got != "/api/v1/namespaces/production/pods" {
		t.Fatalf("namespace path = %q", got)
	}
}

func TestHealthzDoesNotRequireToken(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	testServer().routes().ServeHTTP(w, r)
	if w.Code != http.StatusOK {
		t.Fatalf("healthz status = %d, want %d", w.Code, http.StatusOK)
	}
}

func TestProtectedEndpointRequiresBearerToken(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/api/v1/host", nil)
	w := httptest.NewRecorder()
	testServer().routes().ServeHTTP(w, r)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", w.Code, http.StatusUnauthorized)
	}
}

func TestProtectedEndpointAcceptsConfiguredToken(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "/api/v1/host", nil)
	r.Header.Set("Authorization", "Bearer test-token")
	w := httptest.NewRecorder()
	testServer().routes().ServeHTTP(w, r)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", w.Code, http.StatusOK)
	}
}

func TestSummarizePods(t *testing.T) {
	items := []byte(`{"items":[{"metadata":{"namespace":"prod","name":"ok"},"status":{"phase":"Running","containerStatuses":[{"ready":true,"restartCount":1}]}},{"metadata":{"namespace":"prod","name":"bad"},"status":{"phase":"Running","containerStatuses":[{"ready":false,"restartCount":3,"state":{"waiting":{"reason":"CrashLoopBackOff"}}}]}}]}`)
	var list kubeList
	if err := json.Unmarshal(items, &list); err != nil {
		t.Fatal(err)
	}
	var got PodsSummary
	summarizePods(&got, list.Items)
	if got.Total != 2 || got.Running != 2 || len(got.Items) != 2 || len(got.Unhealthy) != 1 {
		t.Fatalf("unexpected summary: %+v", got)
	}
}
