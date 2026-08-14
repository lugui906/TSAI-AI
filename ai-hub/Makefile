BINARY=aim
BUILD_DIR=build
GO_FLAGS=-ldflags="-s -w"
PREFIX ?= /usr/local
SYSTEMD_DIR ?= /etc/systemd/system

.PHONY: all build clean install uninstall run test lint tidy

all: build

build:
	@mkdir -p $(BUILD_DIR)
	go build -o $(BUILD_DIR)/$(BINARY) $(GO_FLAGS) .

install: build
	@echo "=== Installing $(BINARY) to $(PREFIX) ==="
	install -Dm755 $(BUILD_DIR)/$(BINARY) $(PREFIX)/bin/$(BINARY)
	install -Dm644 scripts/aim.service $(SYSTEMD_DIR)/aim.service
	install -Dm755 scripts/chindows-integrate.sh $(PREFIX)/lib/aim/chindows-integrate.sh
	@echo "Done. Installed binary, systemd service, and integration script."

uninstall:
	rm -f $(PREFIX)/bin/$(BINARY)
	rm -f $(SYSTEMD_DIR)/aim.service
	rm -f $(PREFIX)/lib/aim/chindows-integrate.sh
	@echo "Uninstalled from $(PREFIX)"

run: build
	./$(BUILD_DIR)/$(BINARY)

test:
	go test ./...

lint:
	go vet ./...

tidy:
	go mod tidy

.PHONY: all build clean install uninstall run test lint tidy
