"""In-memory application export. No remote assets or model calls."""
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

INK = colors.HexColor('#272b26')
MUTED = colors.HexColor('#747b70')
LINE = colors.HexColor('#e0e3da')
SOFT = colors.HexColor('#f2f4ec')
GREEN = colors.HexColor('#708558')


def application_pdf(application, profile, request_id, language='es', issued_at=None):
    """Return bytes for a fixed snapshot; the approval service controls release."""
    en = language == 'en'
    def tr(es, english):
        return english if en else es
    def safe(value):
        return escape(str(value or '')).replace('\n', '<br/>')
    issued = issued_at or datetime.now(timezone.utc)
    styles = {
        'title': ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=25, leading=30, textColor=INK, spaceAfter=10),
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=10, leading=15, textColor=INK),
        'label': ParagraphStyle('label', fontName='Helvetica-Bold', fontSize=8, leading=12, textColor=MUTED, spaceAfter=4),
        'small': ParagraphStyle('small', fontName='Helvetica', fontSize=8, leading=12, textColor=MUTED),
        'section': ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=GREEN, spaceBefore=17, spaceAfter=9),
    }
    def p(text, style='body'):
        return Paragraph(safe(text), styles[style])
    def field(label, value):
        return [p(label.upper(), 'label'), p(value)]
    def box(rows, widths):
        table = Table(rows, colWidths=widths, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),12),
            ('RIGHTPADDING',(0,0),(-1,-1),12), ('TOPPADDING',(0,0),(-1,-1),7),
            ('BOTTOMPADDING',(0,0),(-1,-1),8), ('LINEBELOW',(0,0),(-1,-1),0.5,LINE),
        ]))
        return table
    output = BytesIO()
    width = A4[0] - 40*mm
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=36*mm, bottomMargin=25*mm,
                            title=tr('Contrato Lumen · demostración', 'Lumen contract · demonstration'), author='Lumen - fictitious demo',
                            pageCompression=1)
    story = [p(tr('CONTRATO DE ENERGÍA · DEMOSTRACIÓN', 'ENERGY CONTRACT · DEMONSTRATION'), 'label'),
             p(application['plan_name'], 'title'),
             p(tr('Contratación confirmada mediante IBM Verify CIBA', 'Contract confirmed through IBM Verify CIBA')),
             Spacer(1,5*mm)]
    price = f"{Decimal(str(application['price_kwh'])):.4f}".rstrip('0').rstrip('.')
    if not en:
        price = price.replace('.', ',')
    story.append(box([
        [field(tr('Referencia', 'Reference'), application['application_id']), field(tr('Estado', 'Status'), tr('Contratada','Contracted') if application.get('status') == 'contratada' else application.get('status'))],
        [field(tr('Tarifa', 'Plan'), application['plan_name']), field(tr('Precio de energía', 'Energy price'), price + ' EUR/kWh')],
        [field(tr('Fecha de solicitud', 'Application date'), application.get('created_at')), field(tr('Documento (UTC)', 'Document (UTC)'), issued.strftime('%Y-%m-%d %H:%M'))],
    ],[width*0.64,width*0.36]))
    story += [p(tr('Titular y suministro', 'Account holder and supply'), 'section'), box([
        [field(tr('Titular', 'Account holder'), profile.get('full_name')), field('DNI / NIE', profile.get('dni'))],
        [field('IBAN', profile.get('iban')), field(tr('Teléfono', 'Phone'), profile.get('phone'))],
        [field(tr('Correo electrónico', 'Email'), profile.get('email')), field(tr('Provincia', 'Province'), profile.get('province'))],
    ],[width*0.64,width*0.36])]
    address = ', '.join(filter(None,[f"{profile.get('street','')} {profile.get('number','')} {profile.get('floor','')}".strip(), f"{profile.get('postal_code','')} {profile.get('city','')}".strip()]))
    story += [Spacer(1,4*mm), p(tr('DIRECCIÓN DE SUMINISTRO','SUPPLY ADDRESS'),'label'), p(address)]
    if profile.get('note'):
        story += [Spacer(1,4*mm),p(tr('NOTA DE LA SOLICITUD','APPLICATION NOTE'),'label'),p(profile['note'])]
    corporate = [p(tr('Empresa ficticia de demostración','Fictitious demonstration company'),'section'),
        p('Lumen Energía Demo, S.L.'),
        p(tr('Sede social: Avenida de la Luz, 24, 28000 Madrid, España (dirección ficticia).',
             'Registered office: Avenida de la Luz, 24, 28000 Madrid, Spain (fictitious address).'),'small'),
        p(tr('CIF de muestra: B00000000 · Registro ficticio: Tomo DEMO, Folio 01, Hoja LUMEN-001.',
             'Sample tax ID: B00000000 · Fictitious registry: Volume DEMO, Folio 01, File LUMEN-001.'),'small'),
        p('contacto@lumen.example.invalid · lumen.example.invalid','small'),Spacer(1,4*mm),
        p(tr('Contrato ficticio del laboratorio, sin validez comercial ni orden de cobro. Los datos corporativos no identifican a una empresa real.',
             'Fictitious laboratory contract, with no commercial validity or payment order. Corporate details do not identify a real company.'),'small'),
        Spacer(1,3*mm), p(tr('Referencia de contrato: ','Contract reference: ') + request_id,'small')]
    story.append(KeepTogether(corporate))
    def page(canvas, document):
        canvas.saveState()
        # Vector version of the app's existing circular Lumen mark and wordmark.
        x,y = A4[0]-51*mm,A4[1]-22*mm
        palette = ['#b8d68b','#efd582','#f0a282','#d2b2ea','#b8d68b']
        for i in range(120):
            at = i/30
            a,b = colors.HexColor(palette[int(at)]),colors.HexColor(palette[int(at)+1])
            f=at-int(at)
            canvas.setFillColor(colors.Color(a.red+(b.red-a.red)*f,a.green+(b.green-a.green)*f,a.blue+(b.blue-a.blue)*f))
            canvas.wedge(x-9,y-9,x+9,y+9,60-i*3,-3.1,stroke=0,fill=1)
        canvas.setStrokeColor(SOFT);canvas.setLineWidth(4);canvas.circle(x,y,7,stroke=1,fill=0)
        canvas.setFillColor(INK);canvas.setFont('Helvetica-Bold',23);canvas.drawString(x+15,y-7,'lumen')
        canvas.setStrokeColor(LINE);canvas.setLineWidth(.5);canvas.line(20*mm, A4[1]-32*mm,A4[0]-20*mm,A4[1]-32*mm)
        canvas.line(20*mm,19*mm,A4[0]-20*mm,19*mm)
        canvas.setFillColor(MUTED);canvas.setFont('Helvetica',8)
        canvas.drawString(20*mm,14*mm,tr('LABORATORIO LUMEN - DATOS FICTICIOS','LUMEN LABORATORY - FICTITIOUS DATA'))
        canvas.drawRightString(A4[0]-20*mm,14*mm,tr('Página ','Page ')+str(document.page))
        canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()
