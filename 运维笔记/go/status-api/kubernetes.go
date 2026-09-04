package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

type kubeClient struct {
	baseURL, token string
	client         *http.Client
}

func newKubeClient() *kubeClient {
	base := strings.TrimRight(os.Getenv("KUBERNETES_API_URL"), "/")
	if base == "" {
		base = "https://kubernetes.default.svc"
	}
	token := strings.TrimSpace(os.Getenv("KUBERNETES_API_TOKEN"))
	if token == "" {
		tokenBytes, _ := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
		token = strings.TrimSpace(string(tokenBytes))
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	caPath := os.Getenv("KUBERNETES_CA_FILE")
	if caPath == "" {
		caPath = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
	}
	if caBytes, err := os.ReadFile(caPath); err == nil {
		pool, poolErr := x509.SystemCertPool()
		if pool == nil {
			pool = x509.NewCertPool()
		}
		if poolErr == nil && pool.AppendCertsFromPEM(caBytes) {
			transport.TLSClientConfig = &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12}
		}
	}
	return &kubeClient{baseURL: base, token: token, client: &http.Client{Timeout: 4 * time.Second, Transport: transport}}
}

func (k *kubeClient) get(ctx context.Context, path string, out any) error {
	if k.token == "" && os.Getenv("KUBERNETES_API_URL") == "" {
		return fmt.Errorf("kubernetes client is not configured")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, k.baseURL+path, nil)
	if err != nil {
		return err
	}
	if k.token != "" {
		req.Header.Set("Authorization", "Bearer "+k.token)
	}
	resp, err := k.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("kubernetes api returned %s", resp.Status)
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 8<<20)).Decode(out)
}

type kubeVersion struct {
	GitVersion string `json:"gitVersion"`
}
type kubeList struct {
	Items []json.RawMessage `json:"items"`
}
type kubeNode struct {
	Status struct {
		Conditions []struct{ Type, Status string } `json:"conditions"`
	} `json:"status"`
}
type kubePod struct {
	Metadata struct {
		Namespace string `json:"namespace"`
		Name      string `json:"name"`
	} `json:"metadata"`
	Status struct {
		Phase             string `json:"phase"`
		ContainerStatuses []struct {
			Ready        bool  `json:"ready"`
			RestartCount int32 `json:"restartCount"`
			State        struct {
				Waiting *struct {
					Reason string `json:"reason"`
				} `json:"waiting"`
			} `json:"state"`
		} `json:"containerStatuses"`
	} `json:"status"`
}

func (k *kubeClient) collect(ctx context.Context) (KubernetesStatus, PodsSummary) {
	started := time.Now()
	ks := KubernetesStatus{ComponentStatus: ComponentStatus{Status: Healthy, ObservedAt: time.Now()}}
	ps := PodsSummary{ComponentStatus: ComponentStatus{Status: Healthy, ObservedAt: time.Now()}}
	var version kubeVersion
	if err := k.get(ctx, "/version", &version); err != nil {
		ks.Status, ks.Reason = Unknown, "KUBERNETES_UNAVAILABLE"
		ps.Status, ps.Reason = Unknown, "KUBERNETES_UNAVAILABLE"
		return ks, ps
	}
	ks.Version = version.GitVersion
	var nodes kubeList
	if err := k.get(ctx, "/api/v1/nodes", &nodes); err == nil {
		ks.NodeCount = len(nodes.Items)
		for _, raw := range nodes.Items {
			var n kubeNode
			if json.Unmarshal(raw, &n) == nil {
				for _, c := range n.Status.Conditions {
					if c.Type == "Ready" && c.Status == "True" {
						ks.ReadyNodeCount++
						break
					}
				}
			}
		}
		if ks.ReadyNodeCount < ks.NodeCount {
			ks.Status = Degraded
			ks.Reason = "NODE_NOT_READY"
		}
	}
	var pods kubeList
	if err := k.get(ctx, "/api/v1/pods", &pods); err != nil {
		ps.Status, ps.Reason = Degraded, "PODS_UNAVAILABLE"
	} else {
		summarizePods(&ps, pods.Items)
	}
	ks.PodCount = ps.Total
	ks.LatencyMS = time.Since(started).Milliseconds()
	return ks, ps
}

func summarizePods(ps *PodsSummary, items []json.RawMessage) {
	ps.Total = len(items)
	for _, raw := range items {
		var p kubePod
		if json.Unmarshal(raw, &p) != nil {
			ps.Unknown++
			continue
		}
		if p.Status.Phase == "Running" {
			ps.Running++
		}
		if p.Status.Phase == "Pending" {
			ps.Pending++
		}
		if p.Status.Phase == "Failed" {
			ps.Failed++
		}
		if p.Status.Phase == "Succeeded" {
			ps.Succeeded++
		}
		if p.Status.Phase == "Unknown" {
			ps.Unknown++
		}
		ready, restarts, reason := true, int32(0), ""
		for _, c := range p.Status.ContainerStatuses {
			ready = ready && c.Ready
			restarts += c.RestartCount
			if c.State.Waiting != nil && reason == "" {
				reason = c.State.Waiting.Reason
			}
		}
		if p.Status.Phase == "Running" && !ready || reason != "" || p.Status.Phase == "Failed" {
			if len(ps.Unhealthy) < 50 {
				ps.Unhealthy = append(ps.Unhealthy, PodStatus{Namespace: p.Metadata.Namespace, Name: p.Metadata.Name, Phase: p.Status.Phase, Ready: ready, RestartCount: restarts, Reason: reason})
			}
			ps.Status = Degraded
		}
	}
	if ps.Status == Degraded && ps.Reason == "" {
		ps.Reason = "POD_UNHEALTHY"
	}
}
