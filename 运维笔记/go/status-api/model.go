package main

import "time"

type Status string

const (
	Healthy   Status = "healthy"
	Degraded  Status = "degraded"
	Unhealthy Status = "unhealthy"
	Unknown   Status = "unknown"
)

type ComponentStatus struct {
	Status     Status    `json:"status"`
	ObservedAt time.Time `json:"observed_at"`
	Stale      bool      `json:"stale,omitempty"`
	LatencyMS  int64     `json:"latency_ms,omitempty"`
	Reason     string    `json:"reason,omitempty"`
}

type HostStatus struct {
	ComponentStatus
	Hostname         string             `json:"hostname,omitempty"`
	CPUCount         int                `json:"cpu_count,omitempty"`
	Load1            float64            `json:"load_1m,omitempty"`
	MemoryTotalBytes uint64             `json:"memory_total_bytes,omitempty"`
	MemoryUsedBytes  uint64             `json:"memory_used_bytes,omitempty"`
	MemoryUsagePct   float64            `json:"memory_usage_percent,omitempty"`
	Filesystems      []FilesystemStatus `json:"filesystems,omitempty"`
}

type FilesystemStatus struct {
	Mountpoint string  `json:"mountpoint"`
	UsagePct   float64 `json:"usage_percent"`
}

type KubernetesStatus struct {
	ComponentStatus
	Version        string `json:"version,omitempty"`
	NodeCount      int    `json:"node_count"`
	ReadyNodeCount int    `json:"ready_node_count"`
	PodCount       int    `json:"pod_count"`
}

type PodStatus struct {
	Namespace    string `json:"namespace"`
	Name         string `json:"name"`
	Phase        string `json:"phase,omitempty"`
	Ready        bool   `json:"ready"`
	RestartCount int32  `json:"restart_count"`
	Reason       string `json:"reason,omitempty"`
}

type PodsSummary struct {
	ComponentStatus
	Namespace string      `json:"namespace,omitempty"`
	Total     int         `json:"total"`
	Running   int         `json:"running"`
	Pending   int         `json:"pending"`
	Failed    int         `json:"failed"`
	Succeeded int         `json:"succeeded"`
	Unknown   int         `json:"unknown"`
	Items     []PodStatus `json:"items,omitempty"`
	Unhealthy []PodStatus `json:"unhealthy,omitempty"`
}

type MiddlewareStatus struct {
	ComponentStatus
	Name string `json:"name"`
	Type string `json:"type"`
}

type StatusResponse struct {
	SchemaVersion string     `json:"schema_version"`
	RequestID     string     `json:"request_id"`
	Status        Status     `json:"status"`
	ObservedAt    time.Time  `json:"observed_at"`
	Data          StatusData `json:"data"`
	Errors        []string   `json:"errors,omitempty"`
}

type StatusData struct {
	Host        HostStatus         `json:"host"`
	Kubernetes  KubernetesStatus   `json:"kubernetes"`
	Pods        PodsSummary        `json:"pods"`
	Services    []MiddlewareStatus `json:"services"`
	Middlewares []MiddlewareStatus `json:"middlewares"`
}
