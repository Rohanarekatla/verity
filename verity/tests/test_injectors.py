import pytest
from bs4 import BeautifulSoup

from eval.inject import strip_alt, detach_label, reduce_contrast

def test_strip_alt_injector():
    clean_html = '<img src="logo.png" alt="Company Logo" class="header-img">'
    
    # 1. Test Injection
    injected = strip_alt.inject(clean_html, selector="img")
    soup = BeautifulSoup(injected, 'html.parser')
    img = soup.find('img')
    assert not img.has_attr('alt'), "Alt attribute should be removed"
    assert img['data-verity-original-alt'] == "Company Logo", "Original alt should be backed up"
    
    # 2. Test Reversal
    reverted = strip_alt.revert(injected, selector="img")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_img = rev_soup.find('img')
    assert rev_img['alt'] == "Company Logo", "Alt attribute should be restored"
    assert not rev_img.has_attr('data-verity-original-alt'), "Backup attribute should be cleaned up"


def test_detach_label_injector():
    clean_html = '<label for="email-input">Email</label><input id="email-input">'
    
    # 1. Test Injection
    injected = detach_label.inject(clean_html, selector="label")
    soup = BeautifulSoup(injected, 'html.parser')
    label = soup.find('label')
    assert label['for'] == "verity-broken-id", "For attribute should be mangled"
    assert label['data-verity-original-for'] == "email-input", "Original for attribute should be backed up"
    
    # 2. Test Reversal
    reverted = detach_label.revert(injected, selector="label")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_label = rev_soup.find('label')
    assert rev_label['for'] == "email-input", "For attribute should be restored"
    assert not rev_label.has_attr('data-verity-original-for'), "Backup attribute should be cleaned up"


def test_reduce_contrast_injector():
    clean_html = '<p id="target" style="font-size: 16px;">Hello</p>'
    
    # 1. Test Injection
    injected = reduce_contrast.inject(clean_html, selector="#target")
    soup = BeautifulSoup(injected, 'html.parser')
    p = soup.find('p')
    assert "color: #cccccc !important" in p['style'], "Low contrast style should be injected"
    assert p['data-verity-original-style'] == "font-size: 16px;", "Original style should be backed up"
    
    # 2. Test Reversal
    reverted = reduce_contrast.revert(injected, selector="#target")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_p = rev_soup.find('p')
    assert rev_p['style'] == "font-size: 16px;", "Original style should be completely restored"
    assert not rev_p.has_attr('data-verity-original-style'), "Backup attribute should be cleaned up"
    
def test_reduce_contrast_injector_no_style():
    clean_html = '<p id="target">Hello</p>'
    injected = reduce_contrast.inject(clean_html, selector="#target")
    reverted = reduce_contrast.revert(injected, selector="#target")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_p = rev_soup.find('p')
    assert not rev_p.has_attr('style'), "Style attribute should be removed if it didn't exist originally"