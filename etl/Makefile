build-ETLFunction:
	python3.12 -m pip install --only-binary=:all: -r requirements.txt --target "$(ARTIFACTS_DIR)"
	cp aws_handler.py pipeline.py "$(ARTIFACTS_DIR)/"
