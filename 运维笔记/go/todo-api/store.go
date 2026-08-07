package main

import (
	"errors"
	"sync"
)

// 业务里可预期的失败，用 error 表达，而不是 panic
var (
	ErrNotFound = errors.New("todo not found")
	ErrBadTitle = errors.New("title is required")
)

type Todo struct {
	ID        int    `json:"id"`
	Title     string `json:"title"`
	Completed bool   `json:"completed"`
}

type Store struct {
	mu     sync.Mutex
	seq    int
	todos  map[int]Todo
}

func NewStore() *Store {
	return &Store{
		todos: make(map[int]Todo),
	}
}

func (s *Store) List() []Todo {
	s.mu.Lock()
	defer s.mu.Unlock()

	out := make([]Todo, 0, len(s.todos))
	for _, t := range s.todos {
		out = append(out, t)
	}
	return out
}

func (s *Store) Create(title string) (Todo, error) {
	if title == "" {
		return Todo{}, ErrBadTitle
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	s.seq++
	t := Todo{ID: s.seq, Title: title, Completed: false}
	s.todos[t.ID] = t
	return t, nil
}

func (s *Store) Get(id int) (Todo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	t, ok := s.todos[id]
	if !ok {
		return Todo{}, ErrNotFound
	}
	return t, nil
}

func (s *Store) Update(id int, title *string, completed *bool) (Todo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	t, ok := s.todos[id]
	if !ok {
		return Todo{}, ErrNotFound
	}
	if title != nil {
		if *title == "" {
			return Todo{}, ErrBadTitle
		}
		t.Title = *title
	}
	if completed != nil {
		t.Completed = *completed
	}
	s.todos[id] = t
	return t, nil
}

func (s *Store) Delete(id int) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, ok := s.todos[id]; !ok {
		return ErrNotFound
	}
	delete(s.todos, id)
	return nil
}
