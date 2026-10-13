test:
	uv run pytest tests/ -q

hassfest:
	docker run --rm -v "$(PWD):/github/workspace" ghcr.io/home-assistant/hassfest

check: test hassfest
