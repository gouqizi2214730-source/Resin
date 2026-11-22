package main

import (
	"context"
	"fmt"
	"net"
	"os"
	"runtime"
	"strings"
	"sync/atomic"
	"time"

	"github.com/Resinat/Resin/internal/buildinfo"
)

var bootstrapDNSServers = []string{
	"223.5.5.5:53",
	"119.29.29.29:53",
	"8.8.8.8:53",
	"1.1.1.1:53",
}

var dnsRoundRobin uint32

func init() {
	// Support --version / -v flag for quick CLI and CI self-test inspection.
	for _, arg := range os.Args[1:] {
		if arg == "--version" || arg == "-v" {
			fmt.Printf("Resin Core %s (commit=%s, built=%s, %s/%s)\n",
				buildinfo.Version, buildinfo.GitCommit, buildinfo.BuildTime, runtime.GOOS, runtime.GOARCH)
			os.Exit(0)
		}
	}

	// Configure fallback DNS servers when /etc/resolv.conf is missing (e.g. on Android)
	// or when RESIN_BOOTSTRAP_DNS is explicitly set.
	customDNS := strings.TrimSpace(os.Getenv("RESIN_BOOTSTRAP_DNS"))
	needsBootstrap := customDNS != ""
	if !needsBootstrap && runtime.GOOS != "windows" {
		if _, err := os.Stat("/etc/resolv.conf"); os.IsNotExist(err) {
			needsBootstrap = true
		}
	}

	if needsBootstrap {
		servers := append([]string(nil), bootstrapDNSServers...)
		if customDNS != "" {
			parts := strings.FieldsFunc(customDNS, func(r rune) bool {
				return r == ',' || r == ';' || r == ' '
			})
			var parsed []string
			for _, p := range parts {
				p = strings.TrimSpace(p)
				if p == "" {
					continue
				}
				if !strings.Contains(p, ":") {
					p = p + ":53"
				}
				parsed = append(parsed, p)
			}
			if len(parsed) > 0 {
				servers = parsed
			}
		}

		dialer := &net.Dialer{Timeout: 4 * time.Second}
		net.DefaultResolver = &net.Resolver{
			PreferGo: true,
			Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
				idx := atomic.AddUint32(&dnsRoundRobin, 1)
				target := servers[int(idx)%len(servers)]
				return dialer.DialContext(ctx, network, target)
			},
		}
	}
}
