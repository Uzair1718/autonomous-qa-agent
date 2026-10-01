.PHONY: install install-browsers demo test test-integration coverage lint typecheck clean codegen har

install:
	python -m pip install -e .

install-browsers:
	python -m playwright install chromium firefox webkit

demo:
	@echo "Starting demo app and running QA agent..."
	FLASK_PORT=5001 python demo/sample_app/app.py &
	sleep 2
	qa-agent run --url http://localhost:5001
	@pkill -f "demo/sample_app/app.py" || true

test:
	python -m pytest tests/unit/ -v

test-integration:
	python -m pytest tests/integration/ -v -s

coverage:
	python -m pytest tests/unit/ --cov=src --cov-report=html --cov-report=term-missing

lint:
	python -m ruff check src/ tests/

typecheck:
	python -m mypy src/

clean:
	rm -rf reports/*
	touch reports/.gitkeep

codegen:
	python -m playwright codegen http://localhost:5000

har:
	python -m playwright open --save-har=reports/dev.har http://localhost:5000
