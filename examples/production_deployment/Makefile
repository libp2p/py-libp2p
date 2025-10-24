# Simple Makefile for libp2p WebSocket Production Deployment
# Docker-based local testing

.PHONY: help build run stop clean test logs status

# Default target
help:
	@echo "🚀 Simple Production Deployment Commands"
	@echo "========================================"
	@echo ""
	@echo "📦 Build Commands:"
	@echo "  make build          - Build Docker image"
	@echo ""
	@echo "🚀 Run Commands:"
	@echo "  make run            - Start with Docker Compose"
	@echo "  make stop           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo ""
	@echo "🧪 Test Commands:"
	@echo "  make test           - Run production tests"
	@echo ""
	@echo "📊 Monitor Commands:"
	@echo "  make logs           - View logs"
	@echo "  make status         - Check service status"
	@echo ""
	@echo "🧹 Cleanup Commands:"
	@echo "  make clean          - Clean up containers and volumes"
	@echo "  make clean-all      - Clean up everything"

# Build commands
build:
	@echo "🔨 Building production Docker image..."
	docker build -t libp2p-production .

# Run commands
run:
	@echo "🚀 Starting production deployment..."
	docker-compose up -d

stop:
	@echo "🛑 Stopping all services..."
	docker-compose down

restart: stop run

# Test commands
test:
	@echo "🧪 Running production tests..."
	python test_production.py

# Monitor commands
logs:
	@echo "📊 Viewing logs..."
	docker-compose logs -f

status:
	@echo "📊 Checking service status..."
	docker-compose ps

# Cleanup commands
clean:
	@echo "🧹 Cleaning up containers and volumes..."
	docker-compose down -v
	docker system prune -f

clean-all: clean
	@echo "🧹 Cleaning up everything..."
	docker system prune -a -f
	docker volume prune -f

# Development commands
dev-setup:
	@echo "🔧 Setting up development environment..."
	pip install -r requirements.txt

dev-run:
	@echo "🚀 Running in development mode..."
	python main.py

dev-test:
	@echo "🧪 Running development tests..."
	python test_production.py

# Production commands
prod-build: build
	@echo "🏭 Production build complete"

prod-deploy: prod-build run
	@echo "🚀 Production deployment complete"

prod-test: prod-deploy
	@echo "🧪 Running production tests..."
	sleep 10
	python test_production.py

# Quick start
quick-start: dev-setup dev-run
	@echo "⚡ Quick start complete!"

# Default target
.DEFAULT_GOAL := help
