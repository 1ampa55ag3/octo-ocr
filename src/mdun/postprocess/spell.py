"""离线拼写检查（轻量，总增量 < 2MB）。

- 英文：SymSpell（MIT）+ 50k 词频表（604KB，本包 data/ 目录），编辑距离 ≤2；
- 中文：内置高精度易错词对表（KB 级，覆盖高频同音/形近错别字）；
- 语境级中文纠错接口保留（ernie-csc，可选重型包，见 correction.py）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import mdun

# 高精度易错词对（按常见度排序；仅收录"几乎只会错"的配对，避免误报）
ZH_COMMON_PAIRS: list[tuple[str, str]] = [
    ("因该", "应该"), ("以经", "已经"), ("按装", "安装"), ("帐号", "账号"),
    ("松驰", "松弛"), ("既使", "即使"), ("必竟", "毕竟"), ("担误", "耽误"),
    ("锻练", "锻炼"), ("幅射", "辐射"), ("复盖", "覆盖"), ("技俩", "伎俩"),
    ("峻工", "竣工"), ("兰球", "篮球"), ("家俱", "家具"), ("膨涨", "膨胀"),
    ("凭添", "平添"), ("气慨", "气概"), ("倾刻", "顷刻"), ("琐碎", "琐碎"),
    ("像貌", "相貌"), ("欣尝", "欣赏"), ("渲泄", "宣泄"), ("膺品", "赝品"),
    ("迁徒", "迁徙"), ("脏款", "赃款"), ("重迭", "重叠"), ("凑和", "凑合"),
    ("再接再励", "再接再厉"), ("甘败下风", "甘拜下风"), ("世外桃园", "世外桃源"),
    ("一如继往", "一如既往"), ("不能自己", "不能自已"), ("一如即往", "一如既往"),
    ("美仑美奂", "美轮美奂"), ("默守成规", "墨守成规"), ("融汇贯通", "融会贯通"),
    ("砰然心动", "怦然心动"), ("凭心而论", "平心而论"), ("迫不急待", "迫不及待"),
    ("其乐无穷", "其乐无穷"), ("惹事生非", "惹是生非"), ("谈笑风声", "谈笑风生"),
    ("望其项背", "望其项背"), ("悬梁刺骨", "悬梁刺股"), ("一股作气", "一鼓作气"),
    ("走头无路", "走投无路"), ("坐位", "座位"), ("五笔", "无比"), ("相像", "相像"),
    ("过份", "过分"), ("辣手", "棘手"), ("化装品", "化妆品"), ("死心踏地", "死心塌地"),
    ("直接了当", "直截了当"), ("别出心裁", "别出心裁"), ("出奇不意", "出其不意"),
    ("川流不息", "川流不息"), ("唇枪舌箭", "唇枪舌剑"), ("得陇忘蜀", "得陇望蜀"),
]


@dataclass
class SpellItem:
    start: int
    end: int
    word: str
    suggestions: list[str] = field(default_factory=list)
    lang: str = "zh"


_EN_WORD = re.compile(r"[A-Za-z]{3,}")

# 高频拼写错误黑名单（词频表本身收录了部分网络语料错拼，需显式纠正）
EN_MISS_FIX: dict[str, str] = {
    "adress": "address", "recieve": "receive", "recieved": "received", "teh": "the",
    "seperate": "separate", "definately": "definitely", "occured": "occurred",
    "untill": "until", "wierd": "weird", "acheive": "achieve", "alot": "a lot",
    "beleive": "believe", "buisness": "business", "enviroment": "environment",
    "goverment": "government", "occurence": "occurrence", "posession": "possession",
    "priviledge": "privilege", "sucess": "success", "tommorow": "tomorrow",
    "wich": "which", "writting": "writing", "calender": "calendar", "embarass": "embarrass",
}


class SpellChecker:
    """中英文拼写检查（离线、轻量）。"""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else Path(mdun.__file__).parent / "data"
        self._sym = None

    def _symspell(self):
        if self._sym is None:
            from symspellpy import SymSpell

            self._sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
            dict_file = self.data_dir / "en_freq_50k.txt"
            if dict_file.exists():
                self._sym.load_dictionary(str(dict_file), term_index=0, count_index=1, encoding="utf-8")
            else:
                raise RuntimeError(f"英文词表缺失: {dict_file}")
        return self._sym

    def check(self, text: str) -> list[SpellItem]:
        items: list[SpellItem] = []
        # 中文易错对（长词优先）
        occupied: list[tuple[int, int]] = []
        for wrong, right in sorted(ZH_COMMON_PAIRS, key=lambda p: -len(p[0])):
            start = 0
            while True:
                i = text.find(wrong, start)
                if i < 0:
                    break
                if not any(a <= i < b or a < i + len(wrong) <= b for a, b in occupied):
                    items.append(SpellItem(i, i + len(wrong), wrong, [right], "zh"))
                    occupied.append((i, i + len(wrong)))
                start = i + 1
        # 英文
        try:
            sym = self._symspell()
        except Exception:  # noqa: BLE001 词表缺失时仅中文
            sym = None
        for m in _EN_WORD.finditer(text):
            w = m.group()
            if w.isupper() or w.istitle():
                continue
            if any(a <= m.start() < b for a, b in occupied):
                continue
            fix = EN_MISS_FIX.get(w.lower())
            if fix:
                items.append(SpellItem(m.start(), m.end(), w, [fix], "en"))
                continue
            if sym is None:
                continue
            try:
                res = sym.lookup(w.lower(), 2, 2)  # VERBOSITY_CLOSEST
            except Exception:  # noqa: BLE001
                continue
            if res and res[0].distance > 0 and res[0].term.lower() != w.lower():
                items.append(SpellItem(m.start(), m.end(), w, [res[0].term], "en"))
        items.sort(key=lambda x: x.start)
        return items
