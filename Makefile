PYTHON := poetry run python
PLATFORMIO_ENV := PLATFORMIO_CORE_DIR=$(CURDIR)/.platformio PLATFORMIO_SETTING_ENABLE_TELEMETRY=no

.PHONY: install demo dashboard test lint format typecheck check firmware-native firmware-hardware

install:
	poetry install --sync

demo:
	poetry run jarred-drive generate-demo --output data/demo

dashboard:
	poetry run streamlit run src/jarred_drive/dashboard/app.py

test:
	poetry run pytest

lint:
	poetry run ruff check .
	poetry run black --check .

format:
	poetry run ruff check --fix .
	poetry run black .

typecheck:
	poetry run mypy src tests

firmware-native:
	$(PLATFORMIO_ENV) poetry run platformio test -d firmware -e native

firmware-hardware:
	$(PLATFORMIO_ENV) poetry run platformio run -d firmware -e waveshare_esp32s3

check: lint typecheck test firmware-native
	poetry check --lock
