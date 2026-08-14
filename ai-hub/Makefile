.PHONY: all build clean install test run

BINARY=aim
BUILD_DIR=build
GO_FLAGS=-ldflags="-s -w"

all: build

build:
	@mkdir -p $(BUILD_DIR)
	go build -o $(BUILD_DIR)/$(BINARY) $(GO_FLAGS) .
	sudo cp $(BUILD_DIR)/$(BINARY) /home/show/4/custom-root/usr/bin/$(BINARY)
	sudo cp $(BUILD_DIR)/$(BINARY) /bin/$(BINARY)
	@echo "Built and deployed to /home/show/4/custom-root/usr/bin/ and /bin/"

clean:
	rm -rf $(BUILD_DIR)

install: build
	sudo cp $(BUILD_DIR)/$(BINARY) /usr/local/bin/
	@echo "Installed to /usr/local/bin/$(BINARY)"

run: build
	./$(BUILD_DIR)/$(BINARY)

test:
	go test ./...

lint:
	go vet ./...

tidy:
	go mod tidy

service-install: build
	sudo bash scripts/chindows-integrate.sh install

.PHONY: all build clean install run test lint tidy service-install
