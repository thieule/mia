Mau instance workflow runtime cho mot du an (copy thu muc nay thanh projects/<ten-du-an>).

Noi dung:
  config.json   — cau hinh mia (workspace, model, provider, kenh...)
  .env            — khoa API / bien ${...} (KHONG commit)
  workflows/      — pipeline YAML (tuy chinh agent_profiles, duong dan toi ../ai-*/)
  workspace/     — tao thu cong hoac de agent ghi; trong config dung "workspace": "./workspace"

Chay (tu a-agents, hoac cd workflow-runtime):

  python main.py --project-dir projects/<ten-du-an> -w workflows/pipeline.example.yaml --request "…"

- project id (session) mac dinh = ten thu muc du an neu khong truyen -p
