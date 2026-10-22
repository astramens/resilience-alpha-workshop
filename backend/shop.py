"""REARM fictional storefront. Prices, stock and permissions are authoritative here."""
import hashlib
import json
import os
import time
import payments
from uuid import UUID,uuid4
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict,field_validator
from psycopg2.extras import Json,RealDictCursor
from common import customer

CATEGORIES=('pistolets','fusils','arbaletes','lames','effets')
TRANSITIONS={'awaiting_payment':{'cancelled'},'confirmed':{'preparing','cancelled'},'preparing':{'ready','cancelled'},'ready':{'collected','cancelled'},'collected':set(),'cancelled':set()}

class Item(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    product_id:int=Field(gt=0)
    quantity:int=Field(ge=1,le=10)

class Checkout(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    recipient:str=Field(min_length=2,max_length=80)
    items:list[Item]=Field(min_length=1,max_length=30)
    accept_demo:bool
    @field_validator('recipient')
    @classmethod
    def clean_recipient(cls,value):
        if len(value.strip())<2:raise ValueError('Indiquez un nom de plateau fictif.')
        return value.strip()
    @field_validator('items')
    @classmethod
    def unique_products(cls,items):
        if len({i.product_id for i in items})!=len(items):raise ValueError('Produit présent plusieurs fois.')
        return sorted(items,key=lambda i:i.product_id)

def fingerprint(body):
    return hashlib.sha256(json.dumps({'recipient':body.recipient,'items':[i.model_dump() for i in body.items]},sort_keys=True).encode()).hexdigest()

class Product(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    sku:str=Field(min_length=3,max_length=32,pattern=r'^[A-Z0-9-]+$')
    name:str=Field(min_length=3,max_length=100)
    category:str
    description:str=Field(min_length=20,max_length=2000)
    grade:str
    price_cents:int=Field(ge=100,le=1000000)
    stock:int=Field(ge=0,le=10000)
    active:bool=True
    image:str=Field(pattern=r'^prop-(?:[1-9]|1[0-2])\.svg$')
    workshop_note:str=Field(max_length=1000)
    @field_validator('category')
    @classmethod
    def category_exists(cls,v):
        if v not in CATEGORIES:raise ValueError('Catégorie inconnue.')
        return v
    @field_validator('grade')
    @classmethod
    def grade_exists(cls,v):
        if v not in ('A','B','C'):raise ValueError('État inconnu.')
        return v

class ProductUpdate(Product):
    version:int=Field(ge=1)

class StateChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:str

class CustomerAccess(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    enabled:bool


def make_router(connection,current_user):
    router=APIRouter(prefix='/api/shop')
    def staff(user=Depends(current_user)):return user
    def writer(user=Depends(current_user)):
        if user['role'] not in ('admin','operator'):raise HTTPException(403,'Droit opérateur requis.')
        return user
    def admin(user=Depends(current_user)):
        if user['role']!='admin':raise HTTPException(403,'Droit administrateur requis.')
        return user
    def audit(cur,actor,action,target,detail=None):
        cur.execute('INSERT INTO shop_audit(actor,action,target,detail) VALUES (%s,%s,%s,%s)',(actor,action,str(target),Json(detail or {})))
        print(json.dumps({'event':action,'actor':actor,'target':str(target)},ensure_ascii=True),flush=True)
    def order(cur,order_id):
        cur.execute('SELECT id,customer_id,recipient,status,total_cents,created_at,updated_at FROM shop_orders WHERE id=%s',(order_id,))
        row=cur.fetchone()
        cur.execute('SELECT product_id,name,sku,quantity,unit_price_cents FROM shop_order_items WHERE order_id=%s ORDER BY product_id',(order_id,))
        row['items']=cur.fetchall()
        row['number']=f"RA-{row['id']:05d}"
        cur.execute('SELECT state,checkout_url FROM shop_order_payments WHERE order_id=%s',(order_id,))
        payment=cur.fetchone()
        row['payment']='stripe_test' if payment else 'simulated'
        row['payment_status']=payment['state'] if payment else 'simulated'
        row['checkout_url']=payment['checkout_url'] if payment and payment['state']=='pending' and row['status']=='awaiting_payment' else None
        return row
    def payment_row(cur,oid):
        cur.execute('SELECT p.*,o.total_cents FROM shop_order_payments p JOIN shop_orders o ON o.id=p.order_id WHERE p.order_id=%s',(oid,))
        return cur.fetchone()
    def ensure_session(cur,oid):
        payment=payment_row(cur,oid)
        if payment and not payment['session_id'] and payment['state']=='pending':
            session=payments.checkout_session(payment)
            cur.execute('UPDATE shop_order_payments SET session_id=%s,checkout_url=%s,updated_at=NOW() WHERE order_id=%s',(session['id'],session['url'],oid))
        return order(cur,oid)
    def settle(cur,row,session):
        payment=payment_row(cur,row['id'])
        if not payment:raise HTTPException(404,'Paiement introuvable.')
        payments.verify_session(session,payment)
        if not payment['session_id']:
            cur.execute('UPDATE shop_order_payments SET session_id=%s WHERE order_id=%s',(session['id'],row['id']))
        if session.get('status')=='complete' and session.get('payment_status')=='paid':
            if payment['state'] in ('refunded','cancelled','expired'):return order(cur,row['id'])
            intent=session.get('payment_intent')
            if not isinstance(intent,str):raise HTTPException(502,'Référence de paiement absente.')
            if row['status']=='awaiting_payment':
                cur.execute("UPDATE shop_orders SET status='confirmed',updated_at=NOW() WHERE id=%s",(row['id'],))
                audit(cur,'stripe','payment_confirmed',row['id'],{'mode':'test'})
            cur.execute("UPDATE shop_order_payments SET state='paid',payment_intent=%s,checkout_url=NULL,updated_at=NOW() WHERE order_id=%s",(intent,row['id']))
        elif session.get('status')=='expired' and row['status']=='awaiting_payment':
            cur.execute("UPDATE shop_order_payments SET state='expired',checkout_url=NULL WHERE order_id=%s",(row['id'],))
            transition(cur,row,'cancelled','stripe')
        return order(cur,row['id'])
    def transition(cur,row,new_status,actor):
        if new_status==row['status']:return order(cur,row['id'])
        if new_status not in TRANSITIONS.get(row['status'],set()):raise HTTPException(409,'Transition de commande interdite.')
        if new_status=='cancelled':
            payment=payment_row(cur,row['id'])
            if payment and payment['state']=='pending':
                # Close provider Checkout before releasing stock; a paid race is reconciled instead.
                if not payment['session_id']:
                    ensure_session(cur,row['id']);payment=payment_row(cur,row['id'])
                session=payments.retrieve(payment['session_id'])
                payments.verify_session(session,payment)
                if session.get('status')=='open':session=payments.expire(payment['session_id'])
                if session.get('status')!='expired':raise HTTPException(409,'Paiement déjà effectué ou en cours : vérifiez le paiement puis annulez.')
                cur.execute("UPDATE shop_order_payments SET state='cancelled',checkout_url=NULL WHERE order_id=%s",(row['id'],))
            elif payment and payment['state']=='paid':
                payments.refund(payment)
                cur.execute("UPDATE shop_order_payments SET state='refunded',checkout_url=NULL WHERE order_id=%s",(row['id'],))
            cur.execute('SELECT product_id,quantity FROM shop_order_items WHERE order_id=%s ORDER BY product_id',(row['id'],))
            for item in cur.fetchall():
                cur.execute('UPDATE shop_products SET stock=stock+%s,version=version+1,updated_at=NOW() WHERE id=%s AND stock+%s<=10000 RETURNING id',(item['quantity'],item['product_id'],item['quantity']))
                if not cur.fetchone():raise HTTPException(409,'Remise en stock impossible : capacité maximale atteinte.')
        cur.execute('UPDATE shop_orders SET status=%s,updated_at=NOW() WHERE id=%s',(new_status,row['id']))
        audit(cur,actor,'order_status',row['id'],{'from':row['status'],'to':new_status})
        return order(cur,row['id'])

    @router.get('/products')
    def products():
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,sku,name,category,description,grade,price_cents,stock,image,workshop_note FROM shop_products WHERE active=TRUE ORDER BY id')
            return cur.fetchall()

    @router.get('/products/{product_id}')
    def product(product_id:int):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,sku,name,category,description,grade,price_cents,stock,image,workshop_note FROM shop_products WHERE id=%s AND active=TRUE',(product_id,))
            row=cur.fetchone()
            if not row:raise HTTPException(404,'Article introuvable.')
            return row

    @router.post('/orders',status_code=201)
    def checkout(body:Checkout,user=Depends(customer)):
        if not body.accept_demo:raise HTTPException(400,'Confirmez le caractère fictif de la commande.')
        payments.require_ready()
        stripe_mode=os.getenv('PAYMENT_MODE','stripe_test')=='stripe_test'
        digest=fingerprint(body)
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Serialize idempotency per customer; lock stock in sorted order across customers.
            cur.execute('SELECT id,enabled FROM shop_customers WHERE id=%s FOR UPDATE',(user['id'],))
            current=cur.fetchone()
            if not current or not current['enabled']:raise HTTPException(403,'Compte désactivé.')
            cur.execute('SELECT id,fingerprint FROM shop_orders WHERE customer_id=%s AND request_id=%s',(user['id'],str(body.request_id)))
            previous=cur.fetchone()
            if previous:
                if previous['fingerprint']!=digest:raise HTTPException(409,'Cette clé de commande correspond à un autre panier.')
                cur.execute('SELECT id FROM shop_orders WHERE id=%s FOR UPDATE',(previous['id'],))
                return ensure_session(cur,previous['id'])
            lines=[]
            for item in body.items:
                cur.execute('SELECT id,sku,name,price_cents,stock,active FROM shop_products WHERE id=%s FOR UPDATE',(item.product_id,))
                p=cur.fetchone()
                if not p or not p['active']:raise HTTPException(409,'Un article du panier est indisponible.')
                if p['stock']<item.quantity:raise HTTPException(409,f"Stock insuffisant pour {p['name']}.")
                lines.append((p,item.quantity))
            total=sum(p['price_cents']*q for p,q in lines)
            if total>10000000:raise HTTPException(400,'Commande trop élevée pour cette démonstration.')
            cur.execute('INSERT INTO shop_orders(customer_id,request_id,fingerprint,recipient,total_cents) VALUES (%s,%s,%s,%s,%s) RETURNING id',(user['id'],str(body.request_id),digest,body.recipient,total))
            oid=cur.fetchone()['id']
            if stripe_mode:
                cur.execute("UPDATE shop_orders SET status='awaiting_payment' WHERE id=%s",(oid,))
                cur.execute('INSERT INTO shop_order_payments(order_id,attempt,expires_at) VALUES (%s,%s,%s)',(oid,str(uuid4()),int(time.time())+3600))
            for p,q in lines:
                cur.execute('UPDATE shop_products SET stock=stock-%s,version=version+1,updated_at=NOW() WHERE id=%s',(q,p['id']))
                cur.execute('INSERT INTO shop_order_items(order_id,product_id,name,sku,quantity,unit_price_cents) VALUES (%s,%s,%s,%s,%s,%s)',(oid,p['id'],p['name'],p['sku'],q,p['price_cents']))
            audit(cur,'client:'+user['username'],'order_created',oid,{'total_cents':total})
            result=order(cur,oid)
        # Persist reservation before the provider request. Timeout/replay cannot create another order.
        if stripe_mode:
            with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT id FROM shop_orders WHERE id=%s FOR UPDATE',(oid,))
                return ensure_session(cur,oid)
        return result

    @router.get('/payment-config')
    def payment_config():return payments.configuration()[0]

    @router.post('/orders/{order_id}/verify-payment')
    def verify_payment(order_id:int,user=Depends(customer)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,status FROM shop_orders WHERE id=%s AND customer_id=%s FOR UPDATE',(order_id,user['id']))
            row=cur.fetchone()
            if not row:raise HTTPException(404,'Commande introuvable.')
            payment=payment_row(cur,order_id)
            if not payment or payment['state']!='pending':return order(cur,order_id)
            if not payment['session_id']:
                ensure_session(cur,order_id);payment=payment_row(cur,order_id)
            return settle(cur,row,payments.retrieve(payment['session_id']))

    @router.get('/orders')
    def my_orders(user=Depends(customer)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id FROM shop_orders WHERE customer_id=%s ORDER BY id DESC LIMIT 100',(user['id'],))
            return [order(cur,r['id']) for r in cur.fetchall()]

    @router.post('/orders/{order_id}/cancel')
    def cancel(order_id:int,user=Depends(customer)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,status FROM shop_orders WHERE id=%s AND customer_id=%s FOR UPDATE',(order_id,user['id']))
            row=cur.fetchone()
            if not row:raise HTTPException(404,'Commande introuvable.')
            if row['status'] not in ('awaiting_payment','confirmed','cancelled'):raise HTTPException(409,'La préparation a commencé. Contactez le comptoir fictif.')
            return transition(cur,row,'cancelled','client:'+user['username'])

    @router.get('/admin/products')
    def admin_products(user=Depends(staff)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM shop_products ORDER BY id')
            return cur.fetchall()

    @router.post('/admin/products',status_code=201)
    def create_product(body:Product,user=Depends(admin)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('sku:'+body.sku,))
            cur.execute('SELECT id FROM shop_products WHERE sku=%s',(body.sku,))
            if cur.fetchone():raise HTTPException(409,'Référence déjà utilisée.')
            fields=body.model_dump()
            cur.execute('INSERT INTO shop_products(sku,name,category,description,grade,price_cents,stock,active,image,workshop_note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',tuple(fields.values()))
            row=cur.fetchone();audit(cur,user['username'],'product_created',row['id'])
            return row

    @router.post('/admin/products/{product_id}')
    def update_product(product_id:int,body:ProductUpdate,user=Depends(admin)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('sku:'+body.sku,))
            cur.execute('SELECT id FROM shop_products WHERE sku=%s AND id<>%s',(body.sku,product_id))
            if cur.fetchone():raise HTTPException(409,'Référence déjà utilisée.')
            cur.execute('UPDATE shop_products SET sku=%s,name=%s,category=%s,description=%s,grade=%s,price_cents=%s,stock=%s,active=%s,image=%s,workshop_note=%s,version=version+1,updated_at=NOW() WHERE id=%s AND version=%s RETURNING *',tuple(body.model_dump(exclude={'version'}).values())+(product_id,body.version))
            row=cur.fetchone()
            if not row:raise HTTPException(409,'Article modifié entre-temps. Rechargez sa fiche.')
            audit(cur,user['username'],'product_updated',product_id,{'version':row['version']})
            return row

    @router.get('/admin/orders')
    def all_orders(user=Depends(staff)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id FROM shop_orders ORDER BY id DESC LIMIT 200')
            return [order(cur,r['id']) for r in cur.fetchall()]

    @router.post('/admin/orders/{order_id}/status')
    def order_status(order_id:int,body:StateChange,user=Depends(writer)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,status FROM shop_orders WHERE id=%s FOR UPDATE',(order_id,))
            row=cur.fetchone()
            if not row:raise HTTPException(404,'Commande introuvable.')
            return transition(cur,row,body.status,user['username'])

    @router.get('/admin/customers')
    def customers(user=Depends(admin)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT c.id,c.username,c.display_name,c.enabled,c.created_at,COUNT(o.id) AS orders FROM shop_customers c LEFT JOIN shop_orders o ON o.customer_id=c.id GROUP BY c.id ORDER BY c.id DESC LIMIT 200')
            return cur.fetchall()

    @router.post('/admin/customers/{customer_id}/access')
    def access(customer_id:int,body:CustomerAccess,user=Depends(admin)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('UPDATE shop_customers SET enabled=%s WHERE id=%s RETURNING id,enabled',(body.enabled,customer_id))
            row=cur.fetchone()
            if not row:raise HTTPException(404,'Client introuvable.')
            cur.execute('DELETE FROM shop_sessions WHERE customer_id=%s',(customer_id,))
            audit(cur,user['username'],'customer_access',customer_id,{'enabled':body.enabled})
            return row

    @router.get('/admin/overview')
    def overview(user=Depends(staff)):
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS orders,COALESCE(SUM(total_cents) FILTER(WHERE status IN ('confirmed','preparing','ready','collected')),0) AS revenue_cents,COUNT(*) FILTER(WHERE status IN ('confirmed','preparing')) AS pending FROM shop_orders")
            result=dict(cur.fetchone())
            cur.execute('SELECT COUNT(*) AS products,COUNT(*) FILTER(WHERE stock<=3 AND active=TRUE) AS low_stock FROM shop_products')
            result.update(cur.fetchone())
            cur.execute('SELECT COUNT(*) AS customers FROM shop_customers');result.update(cur.fetchone())
            cur.execute('SELECT id,actor,action,target,detail,created_at FROM shop_audit ORDER BY id DESC LIMIT 50');result['events']=cur.fetchall()
            return result
    @router.post('/payments/webhook')
    async def stripe_webhook(request:Request):
        payload=await request.body()
        if len(payload)>65536:raise HTTPException(413,'Notification trop volumineuse.')
        event=payments.verify_webhook(payload,request.headers.get('stripe-signature',''))
        if event.get('type') not in ('checkout.session.completed','checkout.session.expired','checkout.session.async_payment_succeeded'):
            return {'received':True}
        session=(event.get('data') or {}).get('object') or {}
        metadata=session.get('metadata') or {}
        try:oid=int(metadata['rearm_order_id'])
        except (KeyError,ValueError,TypeError):return {'received':True}
        with connection() as conn,conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id,status FROM shop_orders WHERE id=%s FOR UPDATE',(oid,))
            row=cur.fetchone()
            if not row:return {'received':True}
            payment=payment_row(cur,oid)
            if not payment or str(payment['attempt'])!=metadata.get('rearm_attempt'):return {'received':True}
            # Re-read authoritative provider state; never trust browser return parameters.
            settle(cur,row,payments.retrieve(str(session.get('id',''))))
        return {'received':True}
    return router
