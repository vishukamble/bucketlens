build:
	@echo "Syncing templates and static into package..."
	cp -r templates bucketlens/templates
	cp -r static bucketlens/static
	python -m build
	@echo "Cleaning up..."
	rm -rf bucketlens/templates bucketlens/static

publish-test: build
	twine upload --repository testpypi dist/*

publish: build
	twine upload dist/*

clean:
	rm -rf dist/ build/ bucketlens/templates bucketlens/static *.egg-info

.PHONY: build publish-test publish clean
