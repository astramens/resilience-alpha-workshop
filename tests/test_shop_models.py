from pathlib import Path
import sys
from uuid import uuid4
import pytest
from pydantic import ValidationError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from shop import Checkout,Product

@pytest.mark.parametrize('quantity',[-1,0,11,1.5,'1',True])
def test_quantity_is_bounded_integer(quantity):
    with pytest.raises(ValidationError):Checkout(request_id=uuid4(),recipient='Studio test',items=[{'product_id':1,'quantity':quantity}],accept_demo=True)

def test_recipient_and_duplicate_items():
    for recipient,items in [('  ',[{'product_id':1,'quantity':1}]),('Studio',[{'product_id':1,'quantity':1}]*2)]:
        with pytest.raises(ValidationError):Checkout(request_id=uuid4(),recipient=recipient,items=items,accept_demo=True)

def test_external_product_image_is_rejected():
    with pytest.raises(ValidationError):Product(sku='TEST-01',name='Test prop',category='pistolets',description='Pièce de cinéma entièrement factice.',grade='A',price_cents=100,stock=1,image='https://evil.invalid/a.svg',workshop_note='Inspecté')
