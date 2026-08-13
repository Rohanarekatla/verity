"""
eval/inject/reduce_contrast.py
Drops text contrast below 4.5:1.
"""
from bs4 import BeautifulSoup

def inject(html_content: str, selector: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    bad_contrast = "color: #cccccc !important; background-color: #ffffff !important;"
    
    for el in soup.select(selector):
        if el.has_attr('style'):
            el['data-verity-original-style'] = el.get('style', '')
            el['style'] = f"{el['style']}; {bad_contrast}".strip('; ')
        else:
            el['data-verity-original-style'] = "VERITY_NO_STYLE"
            el['style'] = bad_contrast
            
    return str(soup)

def revert(html_content: str, selector: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    for el in soup.select(selector):
        if el.has_attr('data-verity-original-style'):
            original = el.get('data-verity-original-style', '')
            if original == "VERITY_NO_STYLE":
                del el['style']
            else:
                el['style'] = original
            del el['data-verity-original-style']
    return str(soup)