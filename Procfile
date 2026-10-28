web: uvicorn sidequest_api.app:create_app --factory --uds /var/run/cabotage/cabotage.sock
release: litestar --app sidequest_api.app:create_app database upgrade --no-prompt
worker: sidequest-bot
