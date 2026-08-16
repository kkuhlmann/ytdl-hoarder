# Taskfile Quick Reference

## Installation
Install Task runner: https://taskfile.dev/installation/

**macOS:**
```bash
brew install go-task
```

**Linux:**
```bash
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin
```

## Usage
```bash
task <taskname>
```

## Common Workflows

### Starting Fresh
When you want to completely reset everything:
```bash
task clean  # Deletes DB, restarts services
```

### Just clearing pending tasks
Task state lives in PostgreSQL — cancel pending work from the Tasks tab in the UI,
or set `tasks.purge_on_startup: true` in `config.yml` to cancel everything pending at boot.

### Database operations
```bash
task db:reset     # Delete and recreate database
task db:backup    # Backup current database
task db:migrate   # Run migrations
```

### Development workflow

**Backend:**
```bash
task backend:test          # Run all tests
task backend:test-file -- tests/test_example.py  # Run specific test
task backend:format        # Format code with ruff
task backend:lint          # Check code style
task backend:lint-fix      # Auto-fix linting issues
task backend:shell         # Open shell in container
```

**Frontend:**
```bash
task frontend:dev          # Start dev server
task frontend:build        # Production build
task frontend:lint         # Check code style
task frontend:test         # Run tests
task frontend:install      # Install dependencies
```

> `frontend:build`, `frontend:lint`, `frontend:test`, and `frontend:install` fall back to running
> inside the Docker `frontend` container when Node/npm isn't installed on the host
> (start it first with `task dev`). `frontend:dev` needs host npm — the Docker
> equivalent is just `task dev`.

### Monitoring
```bash
task logs              # Follow all logs
task logs-backend      # Follow backend logs only
task tasks:runtime     # Orchestrator state (queued/running jobs; admin cookie)
task stats             # Show container resource usage
```

### Service management
```bash
task published # Start from the published release image (no build)
task update    # Pull a newer release and restart
task up        # Start services (dev, builds from source)
task prod      # Build and start prod from source
task down      # Stop services
task restart   # Restart all services
task build     # Rebuild all images (no cache)
```

`task clean` and `task db:reset` restart in whichever mode was running when you
invoked them, so a published-image install is not dragged into a source build.

## Task Chaining

You can run multiple tasks:
```bash
task down build up  # Stop, rebuild, restart
```

## Full Task List
Run `task --list` to see all available tasks with descriptions.

## Troubleshooting

**Services won't start:**
- Check logs: `task logs`
- Try full rebuild: `task down build up`

**Database issues:**
- Backup first: `task db:backup`
- Then reset: `task db:reset`

**Complete nuclear option:**
```bash
task clean  # Removes everything and starts fresh
```
