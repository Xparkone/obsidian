package main

import "context"

type Collector interface {
	Collect(context.Context) (any, error)
}
