# Empty Chair Local Testing

Use this before merging a feature branch or deploying to Render.

## One-time setup

```bash
make setup
```

This creates `.venv` and installs production plus test dependencies.

## Run Empty Chair locally

```bash
make dev
```

Then open:

```text
http://127.0.0.1:8000
```

Local development uses:

```text
local_empty_chair.db
```

It does not touch the Render/PostgreSQL database.

## Run the smoke-test suite

```bash
make test
```

The tests use a separate disposable database:

```text
test_empty_chair.db
```

The current smoke suite checks:

- `/health`
- login, signup, and forgot-password pages
- private-route authentication redirects
- dashboard
- artists
- bookings
- recovery
- customers
- settings
- creating an artist
- creating and rendering an opening

## Recommended branch workflow

```bash
git checkout main
git pull
git checkout -b feature/my-change

# make your changes

make test
make dev
```

Manually click through the changed feature at `http://127.0.0.1:8000`.

If everything passes:

```bash
git add <only-the-files-you-changed>
git commit -m "Describe the change"
git push -u origin feature/my-change
```

Open a pull request. GitHub Actions will run the same smoke-test suite before merge.

## Reset local data

```bash
make reset-local-db
```

Then restart:

```bash
make dev
```

## Clean the test database

```bash
make clean-test-db
```

Normally pytest removes it automatically.
