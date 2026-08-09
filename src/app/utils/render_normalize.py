"""渲染 HTML 归一化工具（叶子模块）.

独立于 browser_mode 模块，避免 ``browser_mode → http 包 → browser_transport → browser_mode``
的循环导入。http 层的 browser_transport 直接从此模块导入。
"""

from __future__ import annotations

from lxml import etree


def normalize_rendered_html(html: str) -> str:
    """将浏览器渲染后的 HTML 归一化到与服务端原始 HTML 同构.

    主要处理浏览器自动插入的 <tbody>, 使现有的 `table > tr` 直接子选择器继续命中.
    """
    try:
        doc = etree.HTML(html)
        if doc is None:
            return html
        for tb in doc.xpath("//tbody"):  # type: ignore[union-attr]
            parent = tb.getparent()
            if parent is None:
                continue
            idx = list(parent).index(tb)
            for child in reversed(list(tb)):
                parent.insert(idx, child)
            parent.remove(tb)
        # 保留 body 内容; lxml 的 HTML 方法会输出完整文档, 需提取 body 内部
        body = doc.find("body")
        if body is not None:
            inner = "".join(etree.tostring(child, encoding="unicode") for child in body)
            return inner
        return etree.tostring(doc, encoding="unicode")
    except Exception:
        return html
