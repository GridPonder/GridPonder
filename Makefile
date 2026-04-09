SFTP_HOST = 51636171.ssh.w1.strato.hosting
SFTP_USER = stu135248240
SFTP_REMOTE = .

.PHONY: build-game build-site build deploy deploy-site ship setup-deploy \
        benchmark benchmark-suite benchmark-build benchmark-agg

## Install deploy tooling (lftp)
setup-deploy:
	brew install lftp

## Build the Flutter web app and copy it to website/public/game/
build-game:
	cd app && flutter build web --release --base-href /game/
	rm -rf website/public/game
	cp -r app/build/web website/public/game

## Copy and resize pack cover images to website/public/pack-covers/
sync-covers:
	mkdir -p website/public/pack-covers
	@for d in packs/*/; do \
		id=$$(basename $$d); \
		manifest=$$d/manifest.json; \
		[ -f "$$manifest" ] || continue; \
		cover=$$(python3 -c "import json; m=json.load(open('$$manifest')); print(m.get('coverImage',''))" 2>/dev/null); \
		src="$$d$$cover"; \
		[ -n "$$cover" ] && [ -f "$$src" ] || continue; \
		dest="website/public/pack-covers/$$id.png"; \
		sips -Z 600 "$$src" --out "$$dest" >/dev/null 2>&1; \
		echo "  cover: $$id ($$cover)"; \
	done

## Build the Astro website (assumes game already built)
build-site: sync-covers
	cd website && npm install && npm run build

## Build everything: Flutter web + Astro site
build: build-game build-site

## Deploy website/dist/ to Strato via SFTP
## Requires: brew install lftp
## Usage: make deploy  (will prompt for password interactively)
## Or:    SFTP_PASS=secret make deploy  (non-interactive)
deploy:
	@command -v lftp >/dev/null 2>&1 || (echo "lftp not found. Run: make setup-deploy" && exit 1)
	@if [ -n "$(SFTP_PASS)" ]; then \
		lftp -u $(SFTP_USER),$(SFTP_PASS) sftp://$(SFTP_HOST) \
		  -e "mirror --reverse --delete --verbose website/dist/ $(SFTP_REMOTE)/; quit"; \
	else \
		lftp -u $(SFTP_USER) sftp://$(SFTP_HOST) \
		  -e "mirror --reverse --delete --verbose website/dist/ $(SFTP_REMOTE)/; quit"; \
	fi

## Build website only (skip Flutter) and deploy — fast path for docs/page edits
deploy-site: build-site deploy

## Build everything and deploy
ship: build deploy

## Compile the Dart game-loop runner binary (required before benchmarking)
benchmark-build:
	cd tools/benchmark/runner && dart pub get && \
	dart compile exe bin/runner.dart -o runner

## Run the curated level suite across all configured models (fast, ~30 levels)
benchmark-suite: benchmark-build
	cd tools/benchmark && python bench.py --suite curated

## Run the full benchmark across all models and all levels (overnight)
benchmark: benchmark-build
	cd tools/benchmark && python bench.py --all

## Aggregate run results into leaderboard.json (commit the result, then make ship)
benchmark-agg:
	cd tools/benchmark && python aggregate.py
