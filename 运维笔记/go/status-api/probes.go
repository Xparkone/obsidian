package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

type probeConfig struct{ name, kind, target string }

func loadProbeConfigs(key string) []probeConfig {
	var out []probeConfig
	for _, item := range strings.Split(os.Getenv(key), ",") {
		parts := strings.SplitN(strings.TrimSpace(item), "|", 3)
		if len(parts) == 3 && parts[0] != "" {
			out = append(out, probeConfig{name: parts[0], kind: parts[1], target: parts[2]})
		}
	}
	return out
}

func runProbes(ctx context.Context, configs []probeConfig) []MiddlewareStatus {
	result := make([]MiddlewareStatus, 0, len(configs))
	for _, cfg := range configs {
		started := time.Now()
		item := MiddlewareStatus{Name: cfg.name, Type: cfg.kind, ComponentStatus: ComponentStatus{Status: Healthy, ObservedAt: time.Now()}}
		var err error
		switch strings.ToLower(cfg.kind) {
		case "http", "https":
			err = probeHTTP(ctx, cfg.target)
		case "tcp", "redis", "mysql", "kafka":
			err = probeTCP(ctx, cfg.target)
		default:
			err = fmt.Errorf("unsupported probe type")
		}
		item.LatencyMS = time.Since(started).Milliseconds()
		if err != nil {
			item.Status, item.Reason = Unhealthy, "PROBE_FAILED"
		}
		result = append(result, item)
	}
	return result
}

func probeHTTP(ctx context.Context, target string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return err
	}
	resp, err := (&http.Client{Timeout: 2 * time.Second}).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	return nil
}
func probeTCP(ctx context.Context, target string) error {
	d := net.Dialer{Timeout: 2 * time.Second}
	conn, err := d.DialContext(ctx, "tcp", target)
	if err != nil {
		return err
	}
	return conn.Close()
}
