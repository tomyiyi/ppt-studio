# Contributing to ppt-studio

## 基本原则

1. **验证先行**：任何改动先在本地实跑验证，贴出命令与结果再合入。
2. **Conventional Commits**：`feat:` / `fix:` / `docs:` / `ci:` / `refactor:` 等前缀，一句话说清改动。
3. **绝不提交凭据**：API Key、token、私有配置一律不进仓库。

## 本地验证

```bash
python -m compileall scripts
python scripts/analyze_image.py --help
python scripts/boost_ink.py --help
python scripts/run_auto_poc.py --help
python scripts/render_svg.py projects/agentflow-os-launch/svg_output /tmp/ci_render --only 01
```

## 提 PR

- 填写 PR 模板中的改动说明与验证过程
- CI（GitHub Actions）必须全绿
