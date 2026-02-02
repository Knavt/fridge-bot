def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def parse_add_lines(text: str):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]

def parse_delete_nums(text: str):
    cleaned = text.replace(",", " ").replace(";", " ")
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    return sorted(set(nums))

def norm(s: str) -> str:
    return " ".join(s.lower().strip().split())
