# Shared helpers used by both the redesign pipeline (pipeline.py) and the
# from-scratch build pipeline (build.py). Submodules:
#   - clients: side-effect-free service configuration and lazy client factories
#   - generation: local/OpenRouter text generation and HTML admission
#   - images:  hero/background image generation via OpenRouter
#   - deploy:  Vercel CLI deployment helpers
#   - email:   Resend pitch / delivery email helpers
