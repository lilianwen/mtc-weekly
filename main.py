import os
import requests
import markdown
from datetime import datetime, timedelta, timezone

# ========== 配置区 ==========
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
GITHUB_TOKEN = os.environ["MY_GITHUB_TOKEN"]

REPOS = [
    "google/merkle-tree-certificate",
    "cloudflare/merkle-tree-certificate",
    "ietf-wg-acme/draft-ietf-acme-mtlscert",
    "google/trillian",
]

DAYS = 7
MODEL = "deepseek/deepseek-v3.2"

# ========== 工具函数 ==========
def github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def fetch_commits(repo, since):
    url = f"https://api.github.com/repos/{repo}/commits"
    commits = []
    page = 1
    while True:
        resp = requests.get(url, headers=github_headers(), params={
            "since": since.isoformat(),
            "per_page": 100,
            "page": page,
        })
        if resp.status_code != 200:
            print(f"Warning: {repo} commits 返回 {resp.status_code}")
            break
        data = resp.json()
        if not data:
            break
        commits.extend(data)
        page += 1
    return commits


def fetch_issues(repo, since):
    url = f"https://api.github.com/repos/{repo}/issues"
    issues = []
    page = 1
    while True:
        resp = requests.get(url, headers=github_headers(), params={
            "since": since.isoformat(),
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 100,
            "page": page,
        })
        if resp.status_code != 200:
            print(f"Warning: {repo} issues 返回 {resp.status_code}")
            break
        data = resp.json()
        if not data:
            break
        issues.extend(data)
        page += 1
    return issues


def fetch_releases(repo, since):
    url = f"https://api.github.com/repos/{repo}/releases"
    resp = requests.get(url, headers=github_headers(), params={"per_page": 10})
    if resp.status_code != 200:
        return []
    releases = []
    for r in resp.json():
        published = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
        if published >= since:
            releases.append(r)
    return releases


def format_raw_data(repo, commits, issues, releases):
    lines = [f"\n### 仓库: {repo}\n"]
    if commits:
        lines.append(f"**Commits ({len(commits)} 个):**")
        for c in commits[:30]:
            sha = c["sha"][:7]
            msg = c["commit"]["message"].split("\n")[0]
            author = c["commit"]["author"]["name"]
            date = c["commit"]["author"]["date"]
            lines.append(f"- [{sha}] {msg} (by {author}, {date})")
    if issues:
        pure_issues = [i for i in issues if "pull_request" not in i]
        prs = [i for i in issues if "pull_request" in i]
        if prs:
            lines.append(f"\n**Pull Requests ({len(prs)} 个):**")
            for pr in prs[:20]:
                lines.append(f"- #{pr['number']} {pr['title']} (by {pr['user']['login']}, state: {pr['state']})")
        if pure_issues:
            lines.append(f"\n**Issues ({len(pure_issues)} 个):**")
            for iss in pure_issues[:20]:
                lines.append(f"- #{iss['number']} {iss['title']} (by {iss['user']['login']}, state: {iss['state']})")
    if releases:
        lines.append(f"\n**Releases ({len(releases)} 个):**")
        for r in releases:
            lines.append(f"- {r['tag_name']}: {r['name']} ({r['published_at']})")
    if not commits and not issues and not releases:
        lines.append("（本周无更新）")
    return "\n".join(lines)


def call_openrouter(system_prompt, user_prompt):
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        },
    )
    if resp.status_code != 200:
        raise Exception(f"OpenRouter API error: {resp.status_code} {resp.text}")
    return resp.json()["choices"][0]["message"]["content"]


def markdown_to_html(md_text):
    """将 Markdown 文本转换为完整的 HTML 页面"""
    css = """
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
            background-color: #fff;
        }
        h1 { color: #222; border-bottom: 2px solid #eee; padding-bottom: 10px; }
        h2 { color: #444; margin-top: 30px; }
        h3 { color: #555; }
        code {
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.95em;
        }
        pre {
            background-color: #f6f8fa;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
        }
        pre code {
            background-color: transparent;
            padding: 0;
        }
        a { color: #0969da; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
    """
    body = markdown.markdown(md_text, extensions=['fenced_code', 'tables'])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MTC 技术动态周报</title>
    {css}
</head>
<body>
{body}
</body>
</html>"""


# ========== 主流程 ==========
def main():
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    since_str = since.strftime('%Y-%m-%d')

    print(f"正在获取 {len(REPOS)} 个仓库自 {since_str} 以来的更新...")

    all_raw = []
    for repo in REPOS:
        print(f"  处理 {repo}...")
        commits = fetch_commits(repo, since)
        issues = fetch_issues(repo, since)
        releases = fetch_releases(repo, since)
        all_raw.append(format_raw_data(repo, commits, issues, releases))

    raw_text = "\n".join(all_raw)

    if all("（本周无更新）" in block for block in all_raw):
        report = f"# MTC 技术动态周报 ({since_str} ~ {date_str})\n\n本周监控的所有仓库均无更新。"
    else:
        print("正在调用大模型生成摘要...")
        system_prompt = """你是一个技术分析师，专注于 Google 和 Cloudflare 的 MTC（Merkle Tree Certificate，默克尔树证书）技术。
请用中文总结以下 GitHub 仓库的近期更新。

要求：
1. 按仓库分别总结，突出技术上有意义的变动
2. 如果某仓库有多个 commit，请归纳其整体方向，而不是逐条罗列
3. 忽略纯文档修正（如 typo fix）、CI 配置调整等噪音
4. 对于 PR 和 issue，关注那些涉及协议设计、安全性、性能的讨论
5. 整体语气专业但易读，面向有技术背景但不一定深入关注过 MTC 的读者
6. 最后给一个 3-5 条的"重点关注"清单"""

        summary = call_openrouter(system_prompt,
                                  f"以下是各仓库近 {DAYS} 天的更新数据：\n\n{raw_text}")
        report = f"# MTC 技术动态周报 ({since_str} ~ {date_str})\n\n{summary}"

    # 写入 Markdown 文件
    md_filename = f"report-{date_str}.md"
    with open(md_filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Markdown 报告已生成: {md_filename}")

    # 写入 HTML 文件
    html_filename = f"report-{date_str}.html"
    html_content = markdown_to_html(report)
    with open(html_filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML 报告已生成: {html_filename}")


if __name__ == "__main__":
    main()
