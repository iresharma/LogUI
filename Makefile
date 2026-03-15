PYTHON ?= python
LOG_FILE ?= example_logs_large.txt

RUST_DIR := log-loader
RUST_BIN := $(RUST_DIR)/target/release/log-loader

.PHONY: all build run clean

all: run

build: $(RUST_BIN)

$(RUST_BIN):
	cd $(RUST_DIR) && cargo build --release

run: build
	$(PYTHON) app.py $(LOG_FILE)

clean:
	cd $(RUST_DIR) && cargo clean
