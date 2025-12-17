.PHONY: templates act-list act-lint act-test act-test-no-pull act-test-pull act-dry-run


LEAD := $(shell head -n 1 LEAD.md)


all: list

templates:
	sed -i -E "s/@(\w*)/@$(LEAD)/" .github/issue_template.md
	sed -i -E "s/@(\w*)/@$(LEAD)/" .github/pull_request_template.md

# ACT commands for local GitHub Actions testing
# Focused on CKAN 2.11 with Python 3.10
act-list:
	@echo "Listing available workflows and jobs..."
	act -l

act-lint:
	@echo "Running linting checks..."
	act pull_request -j lint

act-test:
	@echo "Running tests for CKAN 2.11 with Python 3.10..."
	act pull_request -j test
	docker ps -a --filter "name=act-" --format "{{.ID}}" | xargs -r docker rm -f

act-test-no-pull:
	@echo "Running tests without pulling images (uses cached)..."
	act pull_request -j test --pull=false

act-test-pull:
	@echo "Running tests with force pull (updates images)..."
	act pull_request -j test --pull=true

act-dry-run:
	@echo "Dry run - showing what would execute..."
	act pull_request -n

act-stop-containers:
	@echo "Stopping all ACT containers..."
	docker ps -a --filter "name=act-" --format "{{.ID}}" | xargs -r docker rm -f
