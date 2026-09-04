package main

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func collectHost(_ context.Context) HostStatus {
	started := time.Now()
	hostname, _ := os.Hostname()
	h := HostStatus{ComponentStatus: ComponentStatus{Status: Healthy, ObservedAt: time.Now()}, Hostname: hostname, CPUCount: runtime.NumCPU()}

	if load, err := readLoad1(); err == nil {
		h.Load1 = load
	} else {
		h.Status = Unknown
		h.Reason = "HOST_METRICS_UNAVAILABLE"
	}
	if total, available, err := readMemInfo(); err == nil && total > 0 {
		h.MemoryTotalBytes = total
		h.MemoryUsedBytes = total - available
		h.MemoryUsagePct = float64(h.MemoryUsedBytes) * 100 / float64(total)
	}
	var stat syscall.Statfs_t
	if err := syscall.Statfs("/", &stat); err == nil && stat.Blocks > 0 {
		used := stat.Blocks - stat.Bfree
		h.Filesystems = []FilesystemStatus{{Mountpoint: "/", UsagePct: float64(used) * 100 / float64(stat.Blocks)}}
	}
	h.LatencyMS = time.Since(started).Milliseconds()
	return h
}

func readLoad1() (float64, error) {
	b, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return 0, err
	}
	fields := strings.Fields(string(b))
	if len(fields) == 0 {
		return 0, fmt.Errorf("invalid loadavg")
	}
	return strconv.ParseFloat(fields[0], 64)
}

func readMemInfo() (total, available uint64, err error) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	s := bufio.NewScanner(f)
	for s.Scan() {
		fields := strings.Fields(s.Text())
		if len(fields) < 2 {
			continue
		}
		value, parseErr := strconv.ParseUint(fields[1], 10, 64)
		if parseErr != nil {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			total = value * 1024
		case "MemAvailable:":
			available = value * 1024
		}
	}
	return total, available, s.Err()
}
