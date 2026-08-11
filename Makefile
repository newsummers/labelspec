.PHONY: install test build run dev-backend dev-frontend

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/pip install -e 'backend[dev]'
	cd frontend && npm install

test:
	.venv/bin/pytest
	cd frontend && npm run build

build:
	cd frontend && npm run build

run: build
	.venv/bin/labelspec serve --host 127.0.0.1 --port 8000

dev-backend:
	.venv/bin/labelspec serve --host 127.0.0.1 --port 8000 --reload

dev-frontend:
	cd frontend && npm run dev

