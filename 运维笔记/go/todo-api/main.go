package main

import (
	"log"
	"net/http"
)

func main() {
	store := NewStore()
	mux := http.NewServeMux()

	mux.HandleFunc("GET /todos", store.handleList)
	mux.HandleFunc("POST /todos", store.handleCreate)
	mux.HandleFunc("GET /todos/{id}", store.handleGet)
	mux.HandleFunc("PATCH /todos/{id}", store.handleUpdate)
	mux.HandleFunc("DELETE /todos/{id}", store.handleDelete)

	addr := ":8080"
	log.Printf("todo API listening on http://localhost%s", addr)
	// ListenAndServe 只会在失败时返回 error；正常运行会一直阻塞
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
