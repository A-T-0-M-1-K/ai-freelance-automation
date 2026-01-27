# 📁 Configuration Profiles

This directory contains **predefined configuration profiles** for different operational modes of the AI Freelance Automation system.

Each profile is a complete, validated, and secure configuration bundle that defines:
- Target freelance platforms
- Supported job types (transcription, translation, copywriting, etc.)
- AI model preferences
- Payment methods
- Language & communication settings
- Resource allocation (CPU/GPU/memory limits)
- Security policies
- Logging & monitoring levels

## 📄 Profile Structure

Each profile is a **directory** with the following files:
profile_name/
├── config.yaml # Main configuration (validated against JSON Schema)
├── secrets.enc # Encrypted secrets (API keys, tokens, credentials)
├── ai_models.json # List of AI models to load (with priorities)
├── platforms.json # Enabled platforms + scraping rules
├── services.json # Active services (e.g., transcription, copywriting)
└── metadata.json # Profile name, version, description, compatibility


> 🔐 **All sensitive data is encrypted** using `AdvancedCryptoSystem` (AES-256-GCM + Argon2).  
> Never commit `secrets.enc` to version control unless it's in a secure vault.

## 🧪 Available Profiles

| Profile             | Use Case                                      | Auto-Selected When                     |
|---------------------|-----------------------------------------------|----------------------------------------|
| `minimal.yaml`      | Low-resource testing (2 CPU, 4GB RAM)         | `--mode minimal` or dev environment    |
| `standard.yaml`     | Daily operation (8+ CPU, GPU, 32GB RAM)       | Default production mode                |
| `enterprise.yaml`   | High-scale, multi-platform, 24/7 operation    | Cluster deployment                     |
| `stealth.yaml`      | Low-profile activity (avoid rate limits)      | Suspicious platform behavior detected   |
| `recovery.yaml`     | Emergency mode (max logging, minimal AI)      | Auto-activated by `EmergencyRecovery`  |

## 🛠️ How to Create a New Profile

1. Copy an existing profile (e.g., `standard/`)
2. Modify `config.yaml` using the [Unified Config Schema](../../schemas/config_schema.json)
3. Run:  
   ```bash
   python -m core.config.config_validator --profile ./my_profile
   
Encrypt secrets:
bash
1
python -m core.security.key_manager --encrypt-secrets ./my_profile
✅ All profiles are hot-reloadable at runtime via DynamicConfigManager.

⚠️ Important Notes
Do not edit profiles manually in production — use the Admin UI or CLI tools.
Profiles are immutable at runtime; changes require validation before activation.
The system automatically switches profiles during emergencies (e.g., DDoS, API ban).
Each profile must pass security audit (audit_logger.py) before activation.
💡 This system enables true autonomy: the AI freelancer can adapt its behavior, risk tolerance, and resource usage based on real-time conditions — all defined through these profiles.