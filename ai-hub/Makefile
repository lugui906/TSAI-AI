BINARY=aim
BUILD_DIR=build
GO_FLAGS=-ldflags="-s -w"
CUSTOM_ROOT=/home/show/4/custom-root

.PHONY: all build clean install uninstall run test lint tidy

all: build

build:
	@mkdir -p $(BUILD_DIR)
	go build -o $(BUILD_DIR)/$(BINARY) $(GO_FLAGS) .

install: build
	@echo "=== Installing $(BINARY) to $(CUSTOM_ROOT) ==="
	install -Dm755 $(BUILD_DIR)/$(BINARY) $(CUSTOM_ROOT)/usr/bin/$(BINARY)
	install -Dm644 scripts/aim.service $(CUSTOM_ROOT)/etc/systemd/system/aim.service
	install -Dm755 scripts/chindows-integrate.sh $(CUSTOM_ROOT)/usr/local/lib/aim/chindows-integrate.sh
	@echo "Done. Installed binary, systemd service, and integration script."

uninstall:
	rm -f $(CUSTOM_ROOT)/usr/bin/$(BINARY)
	rm -f $(CUSTOM_ROOT)/etc/systemd/system/aim.service
	rm -f $(CUSTOM_ROOT)/usr/local/lib/aim/chindows-integrate.sh
	@echo "Uninstalled from $(CUSTOM_ROOT)"

run: build
	./$(BUILD_DIR)/$(BINARY)

test:
	go test ./...

lint:
	go vet ./...

tidy:
	go mod tidy

.PHONY: all build clean install uninstall run test lint tidy
