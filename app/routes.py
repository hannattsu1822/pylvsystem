from datetime import date
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, session, make_response
from werkzeug.utils import secure_filename
from .auth import login_required
from . import mysql
import pandas as pd
from datetime import datetime, date  # Adicionado date
import os
from io import BytesIO
from reportlab.lib.pagesizes import letter
# Adicionado HRFlowable
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER  # Adicionado TA_CENTER

main_bp = Blueprint('main', __name__)

# Configurations
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@main_bp.route('/dashboard')
@login_required
def dashboard():
    try:
        # Dados básicos para teste (substitua com suas consultas reais)
        dados = {
            'total_veiculos': 10,
            'inspecoes_recentes': 5
        }
        return render_template('dashboard.html', **dados)

    except Exception as e:
        flash(f"Erro ao carregar dashboard: {str(e)}", 'error')
        current_app.logger.error(
            f"ERRO NO DASHBOARD: {str(e)}")  # Log no servidor
        return redirect(url_for('main.dashboard'))  # Ou redirecione para login


@main_bp.route('/transformadores')
@login_required
def transformadores():
    try:
        with mysql.connection.cursor() as cur:
            cur.execute("SELECT * FROM transformadores ORDER BY id DESC")
            transformadores = cur.fetchall()
        return render_template('transformadores/main.html', transformadores=transformadores)
    except Exception as e:
        flash(f'Erro ao carregar transformadores: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))


@main_bp.route('/transformadores/upload', methods=['GET', 'POST'])
@login_required
def upload_trafo():
    if request.method == 'POST':
        if 'arquivo' not in request.files:
            flash('Nenhum arquivo enviado', 'error')
            return redirect(request.url)

        file = request.files['arquivo']

        if file.filename == '':
            flash('Nenhum arquivo selecionado', 'error')
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash(
                'Tipo de arquivo não permitido. Use Excel (.xlsx, .xls) ou CSV', 'error')
            return redirect(request.url)

        try:
            filename = secure_filename(file.filename)
            upload_folder = os.path.join(current_app.root_path, 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            filepath = os.path.join(upload_folder, filename)
            file.save(filepath)

            df = pd.read_excel(
                filepath,
                sheet_name='TRANSFORMADORES',
                header=1,
                usecols='A:I'
            )

            df.columns = [
                'item', 'marca', 'potencia', 'numero_fases',
                'numero_serie', 'local_retirada', 'regional',
                'motivo_desativacao', 'data_entrada_almoxarifado'
            ]

            df = df.where(pd.notnull(df), None)

            dados = []
            for _, row in df.iterrows():
                try:
                    data_entrada = None
                    if row['data_entrada_almoxarifado']:
                        if isinstance(row['data_entrada_almoxarifado'], str):
                            data_entrada = datetime.strptime(
                                row['data_entrada_almoxarifado'].split()[
                                    0], '%Y-%m-%d'
                            ).date()
                        else:
                            data_entrada = row['data_entrada_almoxarifado'].date(
                            )

                    dados.append({
                        'item': str(row['item']).strip(),
                        'marca': str(row['marca']).strip() if row['marca'] else None,
                        'potencia': str(row['potencia']).strip() if row['potencia'] else None,
                        'numero_fases': str(row['numero_fases']).strip() if row['numero_fases'] else None,
                        'numero_serie': str(row['numero_serie']).strip(),
                        'local_retirada': str(row['local_retirada']).strip() if row['local_retirada'] else None,
                        'regional': str(row['regional']).strip() if row['regional'] else None,
                        'motivo_desativacao': str(row['motivo_desativacao']).strip() if row['motivo_desativacao'] else None,
                        'data_entrada_almoxarifado': data_entrada
                    })
                except Exception as e:
                    print(f"Erro processando linha {_}: {str(e)}")
                    continue

            success_count = 0
            duplicates = 0
            errors = 0
            with mysql.connection.cursor() as cur:
                for item in dados:
                    try:
                        cur.execute(
                            "SELECT id FROM transformadores WHERE numero_serie = %s",
                            (item['numero_serie'],)
                        )
                        if cur.fetchone():
                            duplicates += 1
                            continue

                        cur.execute("""
                            INSERT INTO transformadores (
                                item, marca, potencia, numero_fases, numero_serie,
                                local_retirada, regional, motivo_desativacao, data_entrada_almoxarifado
                            ) VALUES (
                                %(item)s, %(marca)s, %(potencia)s, %(numero_fases)s, %(numero_serie)s,
                                %(local_retirada)s, %(regional)s, %(motivo_desativacao)s, %(data_entrada_almoxarifado)s
                            )
                        """, item)
                        success_count += 1
                    except Exception as e:
                        print(
                            f"Erro inserindo {item['numero_serie']}: {str(e)}")
                        errors += 1

                mysql.connection.commit()

            os.remove(filepath)

            msg = f"Importação concluída: {success_count} novos registros"
            if duplicates > 0:
                msg += f", {duplicates} duplicados ignorados"
            if errors > 0:
                msg += f", {errors} erros encontrados"

            flash(msg, 'success' if success_count > 0 else 'warning')
            return redirect(url_for('main.transformadores'))

        except Exception as e:
            mysql.connection.rollback()
            if 'filepath' in locals() and os.path.exists(filepath):
                os.remove(filepath)
            flash(f'Erro ao importar arquivo: {str(e)}', 'error')
            return redirect(request.url)

    return render_template('transformadores/upload_trafo.html')


@main_bp.route('/transformadores/inspecao', methods=['GET', 'POST'])
@login_required
def inspecao_trafo():
    if request.method == 'POST':
        try:
            # Processar checkboxes (que enviam listas)
            estado_tanque = ', '.join(request.form.getlist('estado_tanque'))

            # Tratar corrosão especial
            corrosao_tanque = None
            if 'COM CORROSÃO' in estado_tanque:
                corrosao_tanque = request.form.get('corrosao_grau')
                estado_tanque = estado_tanque.replace(
                    'COM CORROSÃO', '').strip()
                if estado_tanque.endswith(','):
                    estado_tanque = estado_tanque[:-1].strip()

            # Processar data de fabricação
            data_fabricacao = None
            if request.form.get('data_fabricacao'):
                data_fabricacao = datetime.strptime(
                    request.form['data_fabricacao'], '%Y-%m-%d').date()

            # Processar reformado
            reformado = request.form.get('reformado') == 'Sim'
            data_reformado = None
            if reformado and request.form.get('data_reformado'):
                data_reformado = datetime.strptime(
                    request.form['data_reformado'], '%Y-%m-%d').date()

            # Processar buchas primárias
            buchas_primarias = ', '.join(
                request.form.getlist('buchas_primarias'))
            if 'Normal' in buchas_primarias and len(buchas_primarias.split(',')) > 1:
                buchas_primarias = 'Normal'

            # Processar buchas secundárias
            buchas_secundarias = ', '.join(
                request.form.getlist('buchas_secundarias'))
            if 'Normal' in buchas_secundarias and len(buchas_secundarias.split(',')) > 1:
                buchas_secundarias = 'Normal'

            # Processar conectores
            conectores = ', '.join(request.form.getlist('conectores'))
            if 'Normal' in conectores and len(conectores.split(',')) > 1:
                conectores = 'Normal'

            with mysql.connection.cursor() as cur:
                form_data = {
                    'numero_serie': request.form['numero_serie'],
                    'detalhes_tanque': estado_tanque,
                    'corrosao_tanque': corrosao_tanque,
                    'data_fabricacao': data_fabricacao,
                    'reformado': reformado,
                    'data_reformado': data_reformado,
                    'buchas_primarias': buchas_primarias,
                    'buchas_secundarias': buchas_secundarias,
                    'conectores': conectores,
                    'avaliacao_bobina_i': request.form['avaliacao_bobina_i'],
                    'avaliacao_bobina_ii': request.form['avaliacao_bobina_ii'],
                    'avaliacao_bobina_iii': request.form['avaliacao_bobina_iii'],
                    'conclusao': request.form['conclusao'],
                    'transformador_destinado': request.form['transformador_destinado'],
                    'matricula_responsavel': session['matricula'],
                    'supervisor_tecnico': 'Eng. Alisson',
                    'observacoes': request.form.get('observacoes', '')
                }

                cur.execute("""
                    INSERT INTO checklist_transformadores (
                        numero_serie, detalhes_tanque, corrosao_tanque,
                        data_fabricacao, reformado, data_reformado,
                        buchas_primarias, buchas_secundarias, conectores,
                        avaliacao_bobina_i, avaliacao_bobina_ii, avaliacao_bobina_iii,
                        conclusao, transformador_destinado, matricula_responsavel,
                        supervisor_tecnico, observacoes, data_formulario
                    ) VALUES (
                        %(numero_serie)s, %(detalhes_tanque)s, %(corrosao_tanque)s,
                        %(data_fabricacao)s, %(reformado)s, %(data_reformado)s,
                        %(buchas_primarias)s, %(buchas_secundarias)s, %(conectores)s,
                        %(avaliacao_bobina_i)s, %(avaliacao_bobina_ii)s, %(avaliacao_bobina_iii)s,
                        %(conclusao)s, %(transformador_destinado)s, %(matricula_responsavel)s,
                        %(supervisor_tecnico)s, %(observacoes)s, NOW()
                    )
                """, form_data)

                mysql.connection.commit()
                flash('Inspeção salva com sucesso!', 'success')
                return redirect(url_for('main.transformadores'))

        except Exception as e:
            mysql.connection.rollback()
            current_app.logger.error(
                f"Erro ao salvar inspeção: {str(e)}", exc_info=True)
            flash(f'Erro ao salvar inspeção: {str(e)}', 'error')
            return redirect(url_for('main.inspecao_trafo'))

    # GET request - mostrar formulário
    with mysql.connection.cursor() as cur:
        # Obter apenas transformadores sem checklist
        cur.execute("""
            SELECT t.numero_serie, t.marca, t.potencia
            FROM transformadores t
            LEFT JOIN checklist_transformadores c ON t.numero_serie = c.numero_serie
            WHERE c.id IS NULL
            ORDER BY t.numero_serie
        """)
        transformadores = cur.fetchall()

        # Obter últimas inspeções para referência
        cur.execute("""
            SELECT c.*, t.item, t.marca, t.potencia
            FROM checklist_transformadores c
            JOIN transformadores t ON c.numero_serie = t.numero_serie
            ORDER BY c.data_formulario DESC
            LIMIT 10
        """)
        checklists = cur.fetchall()

    return render_template(
        'transformadores/inspecao_trafo.html',
        transformadores=transformadores,
        checklists=checklists,
        data_atual=datetime.now().strftime('%d/%m/%Y %H:%M'),
        current_user={
            'nome': session.get('nome'),
            'matricula': session.get('matricula')
        },
        form_data=request.form if request.method == 'POST' else None
    )


@main_bp.route('/transformadores/filtrar')
@login_required
def filtrar_trafos():
    try:
        # Obter parâmetros de filtro
        numero_serie = request.args.get('numero_serie')
        data_inicio = request.args.get('data_inicio')
        data_fim = request.args.get('data_fim')
        conclusao = request.args.getlist('conclusao')
        destinado = request.args.get('destinado')

        # Armazenar filtro na sessão
        session['filtro_atual'] = {
            'numero_serie': numero_serie,
            'data_inicio': data_inicio,
            'data_fim': data_fim,
            'conclusao': conclusao,
            'destinado': destinado
        }

        query = """
            SELECT c.id, c.numero_serie, c.data_formulario, c.conclusao,
                   c.transformador_destinado, t.marca, t.potencia
            FROM checklist_transformadores c
            JOIN transformadores t ON c.numero_serie = t.numero_serie
            WHERE 1=1
        """
        params = []

        if numero_serie:
            query += " AND c.numero_serie LIKE %s"
            params.append(f"%{numero_serie}%")

        if data_inicio:
            query += " AND c.data_formulario >= %s"
            params.append(data_inicio)

        if data_fim:
            query += " AND c.data_formulario <= %s"
            params.append(data_fim)

        if conclusao:
            placeholders = ','.join(['%s'] * len(conclusao))
            query += f" AND c.conclusao IN ({placeholders})"
            params.extend(conclusao)

        if destinado:
            query += " AND c.transformador_destinado = %s"
            params.append(destinado)

        query += " ORDER BY c.data_formulario DESC"

        with mysql.connection.cursor() as cur:
            cur.execute(query, params)
            checklists = cur.fetchall()

        return render_template('transformadores/filtrar_trafo.html',
                               checklists=checklists,
                               current_user={
                                   'matricula': session.get('matricula'),
                                   'nome': session.get('nome'),
                                   'cargo': session.get('cargo')
                               },
                               filtros=session.get('filtro_atual', {}))
    except Exception as e:
        flash(f'Erro ao filtrar inspeções: {str(e)}', 'error')
        return redirect(url_for('main.transformadores'))


@main_bp.route('/transformadores/checklist/<int:id>')
@login_required
def visualizar_checklist(id):
    try:
        with mysql.connection.cursor() as cur:
            # Consulta principal com tratamento absoluto
            cur.execute("""
                SELECT
                    c.id, c.numero_serie, c.detalhes_tanque, c.corrosao_tanque,
                    c.data_fabricacao, c.reformado, c.data_reformado,
                    c.buchas_primarias, c.buchas_secundarias, c.conectores,
                    c.avaliacao_bobina_i, c.avaliacao_bobina_ii, c.avaliacao_bobina_iii,
                    c.conclusao, c.transformador_destinado, c.matricula_responsavel,
                    c.supervisor_tecnico, c.observacoes, c.data_formulario,
                    t.item, t.marca, t.potencia, t.numero_fases
                FROM checklist_transformadores c
                LEFT JOIN transformadores t ON c.numero_serie = t.numero_serie
                WHERE c.id = %s
                LIMIT 1
            """, (id,))

            result = cur.fetchone()

            if not result:
                flash('Checklist não encontrado', 'error')
                return redirect(url_for('main.filtrar_trafos'))

            # Formatação dos dados
            checklist = {
                'id': result['id'],
                'numero_serie': result['numero_serie'] or 'N/A',
                'detalhes_tanque': result['detalhes_tanque'] or 'Nenhuma observação',
                'corrosao_tanque': result['corrosao_tanque'],
                'data_fabricacao': result['data_fabricacao'],
                'reformado': bool(result['reformado']),
                'data_reformado': result['data_reformado'],
                'buchas_primarias': result['buchas_primarias'] or 'Não informado',
                'buchas_secundarias': result['buchas_secundarias'] or 'Não informado',
                'conectores': result['conectores'] or 'Não informado',
                'avaliacao_bobina_i': result['avaliacao_bobina_i'],
                'avaliacao_bobina_ii': result['avaliacao_bobina_ii'],
                'avaliacao_bobina_iii': result['avaliacao_bobina_iii'],
                'conclusao': result['conclusao'],
                'transformador_destinado': result['transformador_destinado'],
                'data_formulario': result['data_formulario'],
                'item': result['item'],
                'marca': result['marca'],
                'potencia': result['potencia'],
                'numero_fases': result['numero_fases'],
                'observacoes': result['observacoes']
            }

            # Processar campos de checkbox para arrays
            for campo in ['detalhes_tanque', 'buchas_primarias', 'buchas_secundarias', 'conectores']:
                checklist[f'{campo}_items'] = checklist[campo].split(
                    ', ') if checklist.get(campo) else []

        return render_template(
            'transformadores/visualizar_checklist.html',
            checklist=checklist,
            current_user={
                'matricula': session.get('matricula'),
                'nome': session.get('nome'),
                'cargo': session.get('cargo')
            }
        )

    except Exception as e:
        current_app.logger.error(
            f"Erro ao carregar checklist: {str(e)}", exc_info=True)
        flash(f'Erro ao carregar checklist: {str(e)}', 'error')
        return redirect(url_for('main.filtrar_trafos'))


@main_bp.route('/transformadores/checklist/<int:id>/pdf')
@login_required
def gerar_pdf_checklist(id):
    try:
        # Obter dados em uma única consulta otimizada
        with mysql.connection.cursor() as cur:
            cur.execute("""
                SELECT
                    c.id, c.numero_serie, c.detalhes_tanque, c.corrosao_tanque,
                    c.data_fabricacao, c.reformado, c.data_reformado,
                    c.buchas_primarias, c.buchas_secundarias, c.conectores,
                    c.avaliacao_bobina_i, c.avaliacao_bobina_ii, c.avaliacao_bobina_iii,
                    c.conclusao, c.transformador_destinado, c.matricula_responsavel,
                    c.supervisor_tecnico, c.observacoes, c.data_formulario,
                    t.item, t.marca, t.potencia, t.numero_fases,
                    t.local_retirada, t.regional, t.motivo_desativacao,
                    t.data_entrada_almoxarifado, u.nome as responsavel_nome
                FROM checklist_transformadores c
                JOIN transformadores t ON c.numero_serie = t.numero_serie
                LEFT JOIN usuarios u ON c.matricula_responsavel = u.matricula
                WHERE c.id = %s
                LIMIT 1
            """, (id,))
            checklist = cur.fetchone()

            if not checklist:
                flash('Checklist não encontrado', 'error')
                return redirect(url_for('main.filtrar_trafos'))

        # Configuração do PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.5*inch,
            rightMargin=0.5*inch,
            topMargin=0.3*inch,
            bottomMargin=0.3*inch
        )

        # Definir estilos antes de criar os elementos
        styles = getSampleStyleSheet()

        # Estilos personalizados
        custom_styles = {
            'title': ParagraphStyle(
                'Title',
                parent=styles['Heading1'],
                fontSize=14,
                leading=16,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12
            ),
            'section': ParagraphStyle(
                'Section',
                parent=styles['Heading2'],
                fontSize=12,
                leading=14,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#3498db'),
                spaceBefore=10,
                spaceAfter=6
            ),
            'label': ParagraphStyle(
                'Label',
                parent=styles['Normal'],
                fontSize=10,
                leading=12,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#2c3e50'),
                leftIndent=0
            ),
            'value': ParagraphStyle(
                'Value',
                parent=styles['Normal'],
                fontSize=10,
                leading=12,
                fontName='Helvetica',
                textColor=colors.black,
                leftIndent=4
            ),
            'value_bold': ParagraphStyle(
                'ValueBold',
                parent=styles['Normal'],
                fontSize=10,
                fontName='Helvetica-Bold'
            ),
            'footer': ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=8,
                alignment=TA_CENTER,
                textColor=colors.gray
            )
        }

        # Função auxiliar para formatar dados
        def format_value(value, default="Não informado"):
            if value is None:
                return default
            if isinstance(value, (datetime, date)):
                return value.strftime('%d/%m/%Y')
            return str(value)

        # Conteúdo do PDF
        elements = []

        # Cabeçalho
        elements.append(
            Paragraph("RELATÓRIO DE INSPEÇÃO DE TRANSFORMADOR", custom_styles['title']))
        elements.append(Paragraph(f"Checklist #{checklist['id']} - {checklist['numero_serie']}",
                                  ParagraphStyle(
            name='Subtitle',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            spaceAfter=16
        )))

        # Divisor visual
        elements.append(HRFlowable(width="100%", thickness=1,
                        spaceAfter=12, color=colors.lightgrey))

        # Seção 1: Informações do Transformador
        elements.append(
            Paragraph("1. INFORMAÇÕES DO TRANSFORMADOR", custom_styles['section']))

        trafo_data = [
            ("Número de Série:", format_value(checklist['numero_serie'])),
            ("Item:", format_value(checklist['item'])),
            ("Marca:", format_value(checklist['marca'])),
            ("Potência:",
             f"{format_value(checklist['potencia'])} kVA" if checklist['potencia'] else "Não informado"),
            ("N° de Fases:", format_value(checklist['numero_fases'])),
            ("Local de Retirada:", format_value(checklist['local_retirada'])),
            ("Regional:", format_value(checklist['regional'])),
            ("Motivo Desativação:", format_value(
                checklist['motivo_desativacao'])),
            ("Data Entrada Almox.:", format_value(
                checklist['data_entrada_almoxarifado']))
        ]

        trafo_table = Table([
            [Paragraph(label, custom_styles['label']),
             Paragraph(value, custom_styles['value'])]
            for label, value in trafo_data
        ], colWidths=[2*inch, 4*inch])

        trafo_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('LEFTPADDING', (1, 0), (1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
        ]))

        elements.append(trafo_table)
        elements.append(Spacer(1, 0.2*inch))

        # Seção 2: Detalhes da Inspeção
        elements.append(Paragraph("2. DETALHES DA INSPEÇÃO",
                        custom_styles['section']))

        inspecao_data = [
            ("Estado do Tanque:", format_value(checklist['detalhes_tanque'])),
            *([("Grau de Corrosão:", format_value(checklist['corrosao_tanque']))]
              if checklist['corrosao_tanque'] else []),
            ("Buchas Primárias:", format_value(checklist['buchas_primarias'])),
            ("Buchas Secundárias:", format_value(
                checklist['buchas_secundarias'])),
            ("Conectores:", format_value(checklist['conectores']))
        ]

        inspecao_table = Table([
            [Paragraph(label, custom_styles['label']),
             Paragraph(value, custom_styles['value'])]
            for label, value in inspecao_data
        ], colWidths=[2*inch, 4*inch])

        inspecao_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('LEFTPADDING', (1, 0), (1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
        ]))

        elements.append(inspecao_table)
        elements.append(Spacer(1, 0.2*inch))

        # Seção 3: Resultados dos Ensaios
        elements.append(Paragraph("3. RESULTADOS DOS ENSAIOS",
                        custom_styles['section']))

        ensaios_data = [
            ("Bobina I:", format_value(checklist['avaliacao_bobina_i'])),
            ("Bobina II:", format_value(checklist['avaliacao_bobina_ii'])),
            ("Bobina III:", format_value(checklist['avaliacao_bobina_iii']))
        ]

        ensaios_table = Table([
            [Paragraph(label, custom_styles['label']), Paragraph(
                value, custom_styles['value_bold'])]
            for label, value in ensaios_data
        ], colWidths=[2*inch, 4*inch])

        ensaios_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('LEFTPADDING', (1, 0), (1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            *([('TEXTCOLOR', (1, 0), (1, 0), colors.green)]
              if checklist['avaliacao_bobina_i'] == 'Normal' else []),
            *([('TEXTCOLOR', (1, 1), (1, 1), colors.green)]
              if checklist['avaliacao_bobina_ii'] == 'Normal' else []),
            *([('TEXTCOLOR', (1, 2), (1, 2), colors.green)] if checklist['avaliacao_bobina_iii'] == 'Normal' else [])
        ]))

        elements.append(ensaios_table)
        elements.append(Spacer(1, 0.2*inch))

        # Seção 4: Conclusão
        elements.append(Paragraph("4. CONCLUSÃO", custom_styles['section']))

        conclusao_data = [
            ("Status:", format_value(checklist['conclusao'])),
            ("Destinação:", format_value(
                checklist['transformador_destinado'])),
            ("Observações:", format_value(
                checklist['observacoes'], "Nenhuma observação"))
        ]

        conclusao_table = Table([
            [Paragraph(label, custom_styles['label']),
             Paragraph(value, custom_styles['value'])]
            for label, value in conclusao_data
        ], colWidths=[2*inch, 4*inch])

        conclusao_color = colors.green if checklist['conclusao'] == 'Normal' else colors.red

        conclusao_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('LEFTPADDING', (1, 0), (1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (1, 0), conclusao_color),
            ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold')
        ]))

        elements.append(conclusao_table)
        elements.append(Spacer(1, 0.3*inch))

        # Seção 5: Responsáveis
        elements.append(Paragraph("5. RESPONSÁVEIS", custom_styles['section']))

        responsavel_text = f"{format_value(checklist['responsavel_nome'])} ({format_value(checklist['matricula_responsavel'])})"

        responsaveis_data = [
            ("Responsável Técnico:", responsavel_text),
            ("Supervisor Técnico:", format_value(
                checklist['supervisor_tecnico'])),
            ("Data da Inspeção:",
             checklist['data_formulario'].strftime('%d/%m/%Y %H:%M'))
        ]

        responsaveis_table = Table([
            [Paragraph(label, custom_styles['label']),
             Paragraph(value, custom_styles['value'])]
            for label, value in responsaveis_data
        ], colWidths=[2*inch, 4*inch])

        responsaveis_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('LEFTPADDING', (1, 0), (1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
        ]))

        elements.append(responsaveis_table)

        # Rodapé
        elements.append(Spacer(1, 0.4*inch))
        elements.append(HRFlowable(width="100%", thickness=1,
                        spaceBefore=6, spaceAfter=6, color=colors.lightgrey))
        elements.append(Paragraph("Sistema de Gestão de Transformadores - Linha Viva",
                                  ParagraphStyle(
                                      name='Footer',
                                      parent=styles['Normal'],
                                      fontSize=8,
                                      alignment=TA_CENTER,
                                      textColor=colors.gray
                                  )))
        elements.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                                  ParagraphStyle(
            name='FooterDate',
            parent=styles['Normal'],
            fontSize=8,
            alignment=TA_CENTER,
            textColor=colors.gray
        )))

        # Construir PDF
        doc.build(elements)

        # Retornar resposta
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = (
            f'attachment; filename='
            f'checklist_{checklist["id"]}_{checklist["numero_serie"]}_'
            f'{datetime.now().strftime("%Y%m%d")}.pdf'
        )

        return response

    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}", exc_info=True)
        flash(f'Erro ao gerar PDF: {str(e)}', 'error')
        return redirect(url_for('main.visualizar_checklist', id=id))


@main_bp.route('/transformadores/checklist/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_checklist(id):
    try:
        if request.method == 'POST':
            # Processar checkboxes
            estado_tanque = ', '.join(
                filter(None, request.form.getlist('estado_tanque')))

            # Tratar corrosão
            corrosao_tanque = None
            if 'COM CORROSÃO' in estado_tanque:
                corrosao_tanque = request.form.get('corrosao_grau')
                estado_tanque = estado_tanque.replace(
                    'COM CORROSÃO', '').strip().rstrip(',')

            # Processar datas
            data_fabricacao = request.form.get('data_fabricacao') or None
            data_reformado = request.form.get('data_reformado') or None

            # Converter para tinyint (1 ou 0)
            reformado = 1 if request.form.get('reformado') == 'Sim' else 0

            # Processar campos múltiplos
            def processar_campo(campo):
                valores = [v for v in request.form.getlist(campo) if v]
                return ', '.join(valores) if valores else None

            buchas_primarias = processar_campo('buchas_primarias')
            buchas_secundarias = processar_campo('buchas_secundarias')
            conectores = processar_campo('conectores')

            # Validar campos obrigatórios
            campos_obrigatorios = {
                'numero_serie': 'Número de série',
                'avaliacao_bobina_i': 'Avaliação da Bobina I',
                'avaliacao_bobina_ii': 'Avaliação da Bobina II',
                'avaliacao_bobina_iii': 'Avaliação da Bobina III',
                'conclusao': 'Conclusão',
                'transformador_destinado': 'Destinação'
            }

            for campo, nome in campos_obrigatorios.items():
                if not request.form.get(campo):
                    flash(f'O campo {nome} é obrigatório', 'error')
                    return redirect(url_for('main.editar_checklist', id=id))

            # Preparar dados
            form_data = {
                'numero_serie': request.form['numero_serie'],
                'detalhes_tanque': estado_tanque or None,
                'corrosao_tanque': corrosao_tanque,
                'data_fabricacao': data_fabricacao,
                'reformado': reformado,
                'data_reformado': data_reformado,
                'buchas_primarias': buchas_primarias,
                'buchas_secundarias': buchas_secundarias,
                'conectores': conectores,
                'avaliacao_bobina_i': request.form['avaliacao_bobina_i'],
                'avaliacao_bobina_ii': request.form['avaliacao_bobina_ii'],
                'avaliacao_bobina_iii': request.form['avaliacao_bobina_iii'],
                'conclusao': request.form['conclusao'],
                'transformador_destinado': request.form['transformador_destinado'],
                'observacoes': request.form.get('observacoes') or None,
                'matricula_responsavel': session['matricula'],
                'id': id
            }

            with mysql.connection.cursor() as cur:
                # Verificar duplicidade de número de série
                if request.form['numero_serie'] != request.form['numero_serie_original']:
                    cur.execute("SELECT id FROM checklist_transformadores WHERE numero_serie = %s AND id != %s",
                                (form_data['numero_serie'], id))
                    if cur.fetchone():
                        flash(
                            'Já existe um checklist com este número de série', 'error')
                        return redirect(url_for('main.editar_checklist', id=id))

                # Atualizar checklist
                cur.execute("""
                    UPDATE checklist_transformadores SET
                        numero_serie = %(numero_serie)s,
                        detalhes_tanque = %(detalhes_tanque)s,
                        corrosao_tanque = %(corrosao_tanque)s,
                        data_fabricacao = %(data_fabricacao)s,
                        reformado = %(reformado)s,
                        data_reformado = %(data_reformado)s,
                        buchas_primarias = %(buchas_primarias)s,
                        buchas_secundarias = %(buchas_secundarias)s,
                        conectores = %(conectores)s,
                        avaliacao_bobina_i = %(avaliacao_bobina_i)s,
                        avaliacao_bobina_ii = %(avaliacao_bobina_ii)s,
                        avaliacao_bobina_iii = %(avaliacao_bobina_iii)s,
                        conclusao = %(conclusao)s,
                        transformador_destinado = %(transformador_destinado)s,
                        observacoes = %(observacoes)s,
                        matricula_responsavel = %(matricula_responsavel)s
                    WHERE id = %(id)s
                """, form_data)

                mysql.connection.commit()
                flash('Checklist atualizado com sucesso!', 'success')
                return redirect(url_for('main.visualizar_checklist', id=id))

        # GET Request
        with mysql.connection.cursor() as cur:
            cur.execute("""
                SELECT c.*, t.marca, t.potencia, t.numero_fases
                FROM checklist_transformadores c
                JOIN transformadores t ON c.numero_serie = t.numero_serie
                WHERE c.id = %s
            """, (id,))
            checklist = cur.fetchone()

            if not checklist:
                flash('Checklist não encontrado', 'error')
                return redirect(url_for('main.filtrar_trafos'))

            # Converter para dicionário
            checklist = dict(checklist)

            # Converter tinyint para booleano
            checklist['reformado'] = bool(checklist['reformado'])

            # Processar campos múltiplos
            for campo in ['detalhes_tanque', 'buchas_primarias', 'buchas_secundarias', 'conectores']:
                checklist[f'{campo}_items'] = checklist[campo].split(
                    ', ') if checklist.get(campo) else []

            # Obter transformadores para dropdown
            cur.execute(
                "SELECT numero_serie, marca, potencia FROM transformadores ORDER BY numero_serie")
            transformadores = cur.fetchall()

        return render_template(
            'transformadores/editar_checklist.html',
            checklist=checklist,
            transformadores=transformadores,
            current_user={
                'nome': session.get('nome'),
                'matricula': session.get('matricula'),
                'cargo': session.get('cargo')
            },
            data_atual=datetime.now().strftime('%d/%m/%Y %H:%M')
        )

    except Exception as e:
        mysql.connection.rollback()
        current_app.logger.error(
            f"Erro ao editar checklist {id}: {str(e)}", exc_info=True)
        flash(f'Erro ao editar checklist: {str(e)}', 'error')
        return redirect(url_for('main.filtrar_trafos'))


@main_bp.route('/transformadores/checklist/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_checklist(id):
    try:
        # Verificar se o usuário tem permissão (apenas Engenheiro ou Técnico podem excluir)
        if session.get('cargo') not in ['Engenheiro', 'Técnico']:
            flash('Você não tem permissão para excluir checklists', 'error')
            return redirect(url_for('main.filtrar_trafos'))

        with mysql.connection.cursor() as cur:
            # Verificar se o checklist existe
            cur.execute(
                "SELECT id FROM checklist_transformadores WHERE id = %s", (id,))
            if not cur.fetchone():
                flash('Checklist não encontrado', 'error')
                return redirect(url_for('main.filtrar_trafos'))

            # Excluir o checklist
            cur.execute(
                "DELETE FROM checklist_transformadores WHERE id = %s", (id,))
            mysql.connection.commit()

            flash('Checklist excluído com sucesso!', 'success')
            return redirect(url_for('main.filtrar_trafos'))

    except Exception as e:
        mysql.connection.rollback()
        current_app.logger.error(
            f"Erro ao excluir checklist {id}: {str(e)}", exc_info=True)
        flash(f'Erro ao excluir checklist: {str(e)}', 'error')
        return redirect(url_for('main.filtrar_trafos'))
    except Exception as e:
        mysql.connection.rollback()
        current_app.logger.error(
            f"Erro ao excluir checklist {id}: {str(e)}", exc_info=True)
        flash(f'Erro ao excluir checklist: {str(e)}', 'error')
        return redirect(url_for('main.filtrar_trafos'))


@main_bp.route('/subestacao')
@login_required
def subestacao():
    return render_template('subestacao.html')


@main_bp.route('/frota')
@login_required
def frota():
    """Rota principal da frota"""
    return render_template('frota/main_frota.html')


@main_bp.route('/frota/nova_inspecao', methods=['GET', 'POST'])
@login_required
def nova_inspecao_frota():
    try:
        with mysql.connection.cursor() as cursor:
            # Buscar veículos e motoristas
            cursor.execute(
                "SELECT id, placa, modelo FROM veiculos ORDER BY placa")
            veiculos = cursor.fetchall()

            cursor.execute(
                "SELECT matricula, nome FROM usuarios WHERE cargo = 'Motorista' ORDER BY nome")
            motoristas = cursor.fetchall()

            if request.method == 'POST':
                # Obter placa do veículo selecionado
                veiculo_id = request.form['veiculo_id']
                cursor.execute(
                    "SELECT placa FROM veiculos WHERE id = %s", (veiculo_id,))
                veiculo = cursor.fetchone()
                if not veiculo:
                    flash('Veículo não encontrado', 'error')
                    return redirect(url_for('main.nova_inspecao_frota'))

                placa = veiculo['placa']
                matricula = request.form['matricula']
                km_atual = request.form['km_atual']
                horimetro = request.form['horimetro']

                # Lista completa de itens do checklist
                itens_checklist = [
                    'buzina', 'cinto_seguranca', 'quebra_sol', 'retrovisor_inteiro',
                    'retrovisor_direito_esquerdo', 'limpador_para_brisa', 'farol_baixa',
                    'farol_alto', 'meia_luz', 'luz_freio', 'luz_re', 'bateria', 'luzes_painel',
                    'seta_direita_esquerdo', 'pisca_alerta', 'luz_interna', 'velocimetro_tacografo',
                    'freios', 'macaco', 'chave_roda', 'triangulo_sinalizacao', 'extintor_incendio',
                    'portas_travas', 'sirene', 'fechamento_janelas', 'para_brisa', 'oleo_motor',
                    'oleo_freio', 'nivel_agua_radiador', 'pneus_estado_calibragem', 'pneu_reserva_estepe',
                    'bancos_encosto_assentos', 'para_choque_dianteiro', 'para_choque_traseiro',
                    'lataria', 'estado_fisico_sky', 'funcionamento_sky', 'sapatas', 'cestos',
                    'comandos', 'lubrificacao', 'ensaio_eletrico', 'cilindros', 'gavetas', 'capas',
                    'nivel_oleo_sky'
                ]

                # Processar avaliação dos itens (1 = Conforme, 0 = Não Conforme, 2 = Não Informado)
                checklist = {}
                for item in itens_checklist:
                    # Default para Conforme se não informado
                    valor = request.form.get(item, '1')
                    checklist[item] = int(valor)  # Converte para inteiro

                # Inserir no banco
                cursor.execute("""
                    INSERT INTO inspecoes (
                        matricula, placa, data_inspecao, km_atual, horimetro,
                        buzina, cinto_seguranca, quebra_sol, retrovisor_inteiro,
                        retrovisor_direito_esquerdo, limpador_para_brisa, farol_baixa,
                        farol_alto, meia_luz, luz_freio, luz_re, bateria, luzes_painel,
                        seta_direita_esquerdo, pisca_alerta, luz_interna, velocimetro_tacografo,
                        freios, macaco, chave_roda, triangulo_sinalizacao, extintor_incendio,
                        portas_travas, sirene, fechamento_janelas, para_brisa, oleo_motor,
                        oleo_freio, nivel_agua_radiador, pneus_estado_calibragem, pneu_reserva_estepe,
                        bancos_encosto_assentos, para_choque_dianteiro, para_choque_traseiro,
                        lataria, estado_fisico_sky, funcionamento_sky, sapatas, cestos,
                        comandos, lubrificacao, ensaio_eletrico, cilindros, gavetas, capas,
                        nivel_oleo_sky, observacoes
                    ) VALUES (
                        %(matricula)s, %(placa)s, NOW(), %(km_atual)s, %(horimetro)s,
                        %(buzina)s, %(cinto_seguranca)s, %(quebra_sol)s, %(retrovisor_inteiro)s,
                        %(retrovisor_direito_esquerdo)s, %(limpador_para_brisa)s, %(farol_baixa)s,
                        %(farol_alto)s, %(meia_luz)s, %(luz_freio)s, %(luz_re)s, %(bateria)s,
                        %(luzes_painel)s, %(seta_direita_esquerdo)s, %(pisca_alerta)s,
                        %(luz_interna)s, %(velocimetro_tacografo)s, %(freios)s, %(macaco)s,
                        %(chave_roda)s, %(triangulo_sinalizacao)s, %(extintor_incendio)s,
                        %(portas_travas)s, %(sirene)s, %(fechamento_janelas)s, %(para_brisa)s,
                        %(oleo_motor)s, %(oleo_freio)s, %(nivel_agua_radiador)s,
                        %(pneus_estado_calibragem)s, %(pneu_reserva_estepe)s,
                        %(bancos_encosto_assentos)s, %(para_choque_dianteiro)s,
                        %(para_choque_traseiro)s, %(lataria)s, %(estado_fisico_sky)s,
                        %(funcionamento_sky)s, %(sapatas)s, %(cestos)s, %(comandos)s,
                        %(lubrificacao)s, %(ensaio_eletrico)s, %(cilindros)s, %(gavetas)s,
                        %(capas)s, %(nivel_oleo_sky)s, %(observacoes)s
                    )
                """, {
                    'matricula': matricula,
                    'placa': placa,
                    'km_atual': km_atual,
                    'horimetro': horimetro,
                    **checklist,
                    'observacoes': request.form.get('observacoes', '')
                })

                mysql.connection.commit()
                flash('Inspeção registrada com sucesso!', 'success')
                return redirect(url_for('main.frota'))

            return render_template('frota/nova_inspecao_frota.html',
                                   veiculos=veiculos,
                                   motoristas=motoristas)

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Erro ao registrar inspeção: {str(e)}', 'error')
        current_app.logger.error(
            f"Erro em nova_inspecao_frota: {str(e)}", exc_info=True)
        return redirect(url_for('main.frota'))


@main_bp.route('/frota/filtrar_inspecoes', methods=['GET', 'POST'])
@login_required
def filtrar_inspecoes_frota():
    try:
        conn = mysql.connection
        cursor = conn.cursor()

        # Handle deletion
        if request.method == 'POST' and 'excluir' in request.form:
            try:
                inspecao_id = int(request.form['excluir'])
                cursor.execute(
                    "DELETE FROM inspecoes WHERE id = %s", (inspecao_id,))
                conn.commit()
                flash('Inspeção excluída com sucesso!', 'success')
            except ValueError:
                flash('ID de inspeção inválido', 'error')
            return redirect(url_for('main.filtrar_inspecoes_frota'))

        # Get filter parameters
        filtros = {
            'placa': request.args.get('placa', ''),
            'matricula': request.args.get('matricula', ''),
            'data_inicio': request.args.get('data_inicio', ''),
            'data_fim': request.args.get('data_fim', '')
        }

        # Build base query
        query = """
            SELECT 
                i.id,
                DATE_FORMAT(i.data_inspecao, '%%d/%%m/%%Y %%H:%%i') as data_formatada,
                i.placa,
                v.modelo as veiculo_modelo,
                u.nome as motorista_nome,
                i.km_atual,
                i.horimetro,
                i.data_inspecao
            FROM inspecoes i
            JOIN veiculos v ON i.placa = v.placa
            JOIN usuarios u ON i.matricula = u.matricula
            WHERE 1=1
        """
        params = []

        # Apply filters
        if filtros['placa']:
            query += " AND i.placa LIKE %s"
            params.append(f"%{filtros['placa']}%")

        if filtros['matricula']:
            query += " AND i.matricula LIKE %s"
            params.append(f"%{filtros['matricula']}%")

        if filtros['data_inicio']:
            query += " AND i.data_inspecao >= %s"
            params.append(filtros['data_inicio'])

        if filtros['data_fim']:
            query += " AND i.data_inspecao <= DATE_ADD(%s, INTERVAL 1 DAY)"
            params.append(filtros['data_fim'])

        query += " ORDER BY i.data_inspecao DESC"

        # Execute query
        cursor.execute(query, params)
        inspecoes = cursor.fetchall()

        # Get data for filter dropdowns
        cursor.execute("SELECT DISTINCT placa FROM veiculos ORDER BY placa")
        placas = [p['placa'] for p in cursor.fetchall()]

        cursor.execute("""
            SELECT DISTINCT u.matricula, u.nome 
            FROM usuarios u
            JOIN inspecoes i ON u.matricula = i.matricula
            WHERE u.cargo = 'Motorista'
            ORDER BY u.nome
        """)
        motoristas = cursor.fetchall()

        return render_template('frota/filtrar_inspecoes_frota.html',
                               inspecoes=inspecoes,
                               placas=placas,
                               motoristas=motoristas,
                               filtros=filtros)

    except Exception as e:
        conn.rollback()
        flash(f'Erro ao filtrar inspeções: {str(e)}', 'error')
        current_app.logger.error(
            f"Erro em filtrar_inspecoes_frota: {str(e)}", exc_info=True)
        return redirect(url_for('main.frota'))
    finally:
        cursor.close()


@main_bp.route('/frota/inspecao/<int:id>')
@login_required
def visualizar_inspecao_frota(id):
    try:
        with mysql.connection.cursor() as cur:
            # Buscar dados da inspeção
            cur.execute("""
                SELECT 
                    i.*, 
                    v.modelo as veiculo_modelo, 
                    u.nome as motorista_nome,
                    DATE_FORMAT(i.data_inspecao, '%%d/%%m/%%Y %%H:%%i') as data_formatada
                FROM inspecoes i
                JOIN veiculos v ON i.placa = v.placa
                JOIN usuarios u ON i.matricula = u.matricula
                WHERE i.id = %s
            """, (id,))

            inspecao = cur.fetchone()

            if not inspecao:
                flash('Inspeção não encontrada', 'error')
                return redirect(url_for('main.filtrar_inspecoes_frota'))

            # Converter para dicionário para facilitar o acesso
            inspecao = dict(inspecao)

            # Lista de todos os itens do checklist para exibição
            itens_checklist = [
                ('buzina', 'Buzina'),
                ('cinto_seguranca', 'Cinto de Segurança'),
                ('quebra_sol', 'Quebra Sol'),
                ('retrovisor_inteiro', 'Retrovisor Inteiro'),
                ('retrovisor_direito_esquerdo', 'Retrovisor Direito/Esquerdo'),
                ('limpador_para_brisa', 'Limpador de Para-brisa'),
                ('farol_baixa', 'Farol Baixa'),
                ('farol_alto', 'Farol Alto'),
                ('meia_luz', 'Meia Luz'),
                ('luz_freio', 'Luz de Freio'),
                ('luz_re', 'Luz de Ré'),
                ('bateria', 'Bateria'),
                ('luzes_painel', 'Luzes do Painel'),
                ('seta_direita_esquerdo', 'Seta Direita/Esquerdo'),
                ('pisca_alerta', 'Pisca Alerta'),
                ('luz_interna', 'Luz Interna'),
                ('velocimetro_tacografo', 'Velocímetro/Tacógrafo'),
                ('freios', 'Freios'),
                ('macaco', 'Macaco'),
                ('chave_roda', 'Chave de Roda'),
                ('triangulo_sinalizacao', 'Triângulo de Sinalização'),
                ('extintor_incendio', 'Extintor de Incêndio'),
                ('portas_travas', 'Portas/Travas'),
                ('sirene', 'Sirene'),
                ('fechamento_janelas', 'Fechamento de Janelas'),
                ('para_brisa', 'Para-brisa'),
                ('oleo_motor', 'Óleo do Motor'),
                ('oleo_freio', 'Óleo de Freio'),
                ('nivel_agua_radiador', 'Nível de Água do Radiador'),
                ('pneus_estado_calibragem', 'Pneus - Estado/Calibragem'),
                ('pneu_reserva_estepe', 'Pneu Reserva/Estepe'),
                ('bancos_encosto_assentos', 'Bancos/Encosto/Assentos'),
                ('para_choque_dianteiro', 'Para-choque Dianteiro'),
                ('para_choque_traseiro', 'Para-choque Traseiro'),
                ('lataria', 'Lataria'),
                ('estado_fisico_sky', 'Estado Físico SKY'),
                ('funcionamento_sky', 'Funcionamento SKY'),
                ('sapatas', 'Sapatas'),
                ('cestos', 'Cestos'),
                ('comandos', 'Comandos'),
                ('lubrificacao', 'Lubrificação'),
                ('ensaio_eletrico', 'Ensaio Elétrico'),
                ('cilindros', 'Cilindros'),
                ('gavetas', 'Gavetas'),
                ('capas', 'Capas'),
                ('nivel_oleo_sky', 'Nível de Óleo SKY')
            ]

            # Preparar dados para o template
            checklist_status = []
            for campo, descricao in itens_checklist:
                valor = inspecao.get(campo, 2)  # Default 2 (Não Informado)
                status = {
                    'descricao': descricao,
                    'valor': valor,
                    'status': 'Conforme' if valor == 1 else 'Não Conforme' if valor == 0 else 'Não Informado'
                }
                checklist_status.append(status)

            return render_template('frota/visualizar_inspecao_frota.html',
                                   inspecao=inspecao,
                                   checklist_status=checklist_status,
                                   current_user={
                                       'matricula': session.get('matricula'),
                                       'nome': session.get('nome'),
                                       'cargo': session.get('cargo')
                                   })

    except Exception as e:
        flash(f'Erro ao carregar inspeção: {str(e)}', 'error')
        current_app.logger.error(
            f"Erro em visualizar_inspecao_frota: {str(e)}", exc_info=True)
        return redirect(url_for('main.filtrar_inspecoes_frota'))


@main_bp.route('/frota/editar_inspecao/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_inspecao_frota(id):
    try:
        conn = mysql.connection
        cursor = conn.cursor()

        if request.method == 'POST':
            # Obter dados do formulário
            placa = request.form['placa']
            matricula = request.form['matricula']
            km_atual = request.form['km_atual']
            horimetro = request.form['horimetro']

            # Processar checklist
            checklist = {}
            itens_checklist = [
                'buzina', 'cinto_seguranca', 'quebra_sol', 'retrovisor_inteiro',
                'retrovisor_direito_esquerdo', 'limpador_para_brisa', 'farol_baixa',
                'farol_alto', 'meia_luz', 'luz_freio', 'luz_re', 'bateria', 'luzes_painel',
                'seta_direita_esquerdo', 'pisca_alerta', 'luz_interna', 'velocimetro_tacografo',
                'freios', 'macaco', 'chave_roda', 'triangulo_sinalizacao', 'extintor_incendio',
                'portas_travas', 'sirene', 'fechamento_janelas', 'para_brisa', 'oleo_motor',
                'oleo_freio', 'nivel_agua_radiador', 'pneus_estado_calibragem', 'pneu_reserva_estepe',
                'bancos_encosto_assentos', 'para_choque_dianteiro', 'para_choque_traseiro',
                'lataria', 'estado_fisico_sky', 'funcionamento_sky', 'sapatas', 'cestos',
                'comandos', 'lubrificacao', 'ensaio_eletrico', 'cilindros', 'gavetas', 'capas',
                'nivel_oleo_sky'
            ]

            for item in itens_checklist:
                checklist[item] = int(request.form.get(
                    item, '1'))  # Default para Conforme

            # Atualizar no banco
            cursor.execute("""
                UPDATE inspecoes SET
                    placa = %s,
                    matricula = %s,
                    km_atual = %s,
                    horimetro = %s,
                    buzina = %s,
                    cinto_seguranca = %s,
                    quebra_sol = %s,
                    retrovisor_inteiro = %s,
                    retrovisor_direito_esquerdo = %s,
                    limpador_para_brisa = %s,
                    farol_baixa = %s,
                    farol_alto = %s,
                    meia_luz = %s,
                    luz_freio = %s,
                    luz_re = %s,
                    bateria = %s,
                    luzes_painel = %s,
                    seta_direita_esquerdo = %s,
                    pisca_alerta = %s,
                    luz_interna = %s,
                    velocimetro_tacografo = %s,
                    freios = %s,
                    macaco = %s,
                    chave_roda = %s,
                    triangulo_sinalizacao = %s,
                    extintor_incendio = %s,
                    portas_travas = %s,
                    sirene = %s,
                    fechamento_janelas = %s,
                    para_brisa = %s,
                    oleo_motor = %s,
                    oleo_freio = %s,
                    nivel_agua_radiador = %s,
                    pneus_estado_calibragem = %s,
                    pneu_reserva_estepe = %s,
                    bancos_encosto_assentos = %s,
                    para_choque_dianteiro = %s,
                    para_choque_traseiro = %s,
                    lataria = %s,
                    estado_fisico_sky = %s,
                    funcionamento_sky = %s,
                    sapatas = %s,
                    cestos = %s,
                    comandos = %s,
                    lubrificacao = %s,
                    ensaio_eletrico = %s,
                    cilindros = %s,
                    gavetas = %s,
                    capas = %s,
                    nivel_oleo_sky = %s,
                    observacoes = %s
                WHERE id = %s
            """, (
                placa, matricula, km_atual, horimetro,
                checklist['buzina'], checklist['cinto_seguranca'], checklist['quebra_sol'],
                checklist['retrovisor_inteiro'], checklist['retrovisor_direito_esquerdo'],
                checklist['limpador_para_brisa'], checklist['farol_baixa'], checklist['farol_alto'],
                checklist['meia_luz'], checklist['luz_freio'], checklist['luz_re'],
                checklist['bateria'], checklist['luzes_painel'], checklist['seta_direita_esquerdo'],
                checklist['pisca_alerta'], checklist['luz_interna'], checklist['velocimetro_tacografo'],
                checklist['freios'], checklist['macaco'], checklist['chave_roda'],
                checklist['triangulo_sinalizacao'], checklist['extintor_incendio'],
                checklist['portas_travas'], checklist['sirene'], checklist['fechamento_janelas'],
                checklist['para_brisa'], checklist['oleo_motor'], checklist['oleo_freio'],
                checklist['nivel_agua_radiador'], checklist['pneus_estado_calibragem'],
                checklist['pneu_reserva_estepe'], checklist['bancos_encosto_assentos'],
                checklist['para_choque_dianteiro'], checklist['para_choque_traseiro'],
                checklist['lataria'], checklist['estado_fisico_sky'], checklist['funcionamento_sky'],
                checklist['sapatas'], checklist['cestos'], checklist['comandos'],
                checklist['lubrificacao'], checklist['ensaio_eletrico'], checklist['cilindros'],
                checklist['gavetas'], checklist['capas'], checklist['nivel_oleo_sky'],
                request.form.get('observacoes', ''),
                id
            ))

            conn.commit()
            flash('Inspeção atualizada com sucesso!', 'success')
            return redirect(url_for('main.visualizar_inspecao_frota', id=id))

        # GET - Carregar dados para edição
        cursor.execute("""
            SELECT i.*, v.modelo as veiculo_modelo, u.nome as motorista_nome 
            FROM inspecoes i
            JOIN veiculos v ON i.placa = v.placa
            JOIN usuarios u ON i.matricula = u.matricula
            WHERE i.id = %s
        """, (id,))

        inspecao = cursor.fetchone()
        if not inspecao:
            flash('Inspeção não encontrada', 'error')
            return redirect(url_for('main.filtrar_inspecoes_frota'))

        # Buscar veículos e motoristas para os selects
        cursor.execute("SELECT placa, modelo FROM veiculos ORDER BY placa")
        veiculos = cursor.fetchall()

        cursor.execute(
            "SELECT matricula, nome FROM usuarios WHERE cargo = 'Motorista' ORDER BY nome"
        )
        motoristas = cursor.fetchall()

        return render_template('frota/editar_inspecao_frota.html',
                               inspecao=inspecao,
                               veiculos=veiculos,
                               motoristas=motoristas)

    except Exception as e:
        conn.rollback()
        flash(f'Erro ao editar inspeção: {str(e)}', 'error')
        current_app.logger.error(
            f"Erro em editar_inspecao_frota: {str(e)}", exc_info=True)
        return redirect(url_for('main.filtrar_inspecoes_frota'))
    finally:
        cursor.close()


@main_bp.route('/frota/inspecao/<int:id>/pdf')
@login_required
def gerar_pdf_inspecao_frota(id):
    try:
        with mysql.connection.cursor() as cur:
            # Buscar dados completos da inspeção
            cur.execute("""
                SELECT 
                    i.*, 
                    v.modelo as veiculo_modelo, 
                    u.nome as motorista_nome,
                    u.nome as responsavel_nome
                FROM inspecoes i
                JOIN veiculos v ON i.placa = v.placa
                JOIN usuarios u ON i.matricula = u.matricula
                WHERE i.id = %s
            """, (id,))

            inspecao = cur.fetchone()

            if not inspecao:
                flash('Inspeção não encontrada', 'error')
                return redirect(url_for('main.filtrar_inspecoes_frota'))

            inspecao = dict(inspecao)

            # Lista completa de itens do checklist
            checklist_items = [
                ('1. Itens Básicos', [
                    ('Buzina', inspecao['buzina']),
                    ('Cinto de Segurança', inspecao['cinto_seguranca']),
                    ('Quebra Sol', inspecao['quebra_sol']),
                    ('Retrovisor Inteiro', inspecao['retrovisor_inteiro']),
                    ('Retrovisor Direito/Esquerdo',
                     inspecao['retrovisor_direito_esquerdo']),
                    ('Limpador de Para-brisa', inspecao['limpador_para_brisa'])
                ]),
                ('2. Iluminação', [
                    ('Farol Baixa', inspecao['farol_baixa']),
                    ('Farol Alto', inspecao['farol_alto']),
                    ('Meia Luz', inspecao['meia_luz']),
                    ('Luz de Freio', inspecao['luz_freio']),
                    ('Luz de Ré', inspecao['luz_re']),
                    ('Bateria', inspecao['bateria']),
                    ('Luzes do Painel', inspecao['luzes_painel']),
                    ('Seta Direita/Esquerdo',
                     inspecao['seta_direita_esquerdo']),
                    ('Pisca Alerta', inspecao['pisca_alerta']),
                    ('Luz Interna', inspecao['luz_interna'])
                ]),
                ('3. Mecânica', [
                    ('Velocímetro/Tacógrafo',
                     inspecao['velocimetro_tacografo']),
                    ('Freios', inspecao['freios']),
                    ('Macaco', inspecao['macaco']),
                    ('Chave de Roda', inspecao['chave_roda']),
                    ('Triângulo de Sinalização',
                     inspecao['triangulo_sinalizacao']),
                    ('Extintor de Incêndio', inspecao['extintor_incendio']),
                    ('Portas/Travas', inspecao['portas_travas']),
                    ('Sirene', inspecao['sirene']),
                    ('Fechamento de Janelas', inspecao['fechamento_janelas']),
                    ('Para-brisa', inspecao['para_brisa']),
                    ('Óleo do Motor', inspecao['oleo_motor']),
                    ('Óleo de Freio', inspecao['oleo_freio']),
                    ('Nível de Água do Radiador',
                     inspecao['nivel_agua_radiador'])
                ]),
                ('4. Pneus e Estrutura', [
                    ('Pneus - Estado/Calibragem',
                     inspecao['pneus_estado_calibragem']),
                    ('Pneu Reserva/Estepe', inspecao['pneu_reserva_estepe']),
                    ('Bancos/Encosto/Assentos',
                     inspecao['bancos_encosto_assentos']),
                    ('Para-choque Dianteiro',
                     inspecao['para_choque_dianteiro']),
                    ('Para-choque Traseiro', inspecao['para_choque_traseiro']),
                    ('Lataria', inspecao['lataria'])
                ]),
                ('5. Equipamento SKY', [
                    ('Estado Físico SKY', inspecao['estado_fisico_sky']),
                    ('Funcionamento SKY', inspecao['funcionamento_sky']),
                    ('Sapatas', inspecao['sapatas']),
                    ('Cestos', inspecao['cestos']),
                    ('Comandos', inspecao['comandos']),
                    ('Lubrificação', inspecao['lubrificacao']),
                    ('Ensaio Elétrico', inspecao['ensaio_eletrico']),
                    ('Cilindros', inspecao['cilindros']),
                    ('Gavetas', inspecao['gavetas']),
                    ('Capas', inspecao['capas']),
                    ('Nível de Óleo SKY', inspecao['nivel_oleo_sky'])
                ])
            ]

            # Preparar buffer para o PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                leftMargin=0.5*inch,
                rightMargin=0.5*inch,
                topMargin=0.5*inch,
                bottomMargin=0.5*inch
            )

            # Estilos para o PDF
            styles = getSampleStyleSheet()

            # Estilos personalizados
            title_style = ParagraphStyle(
                'Title',
                parent=styles['Heading1'],
                fontSize=14,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12
            )

            subtitle_style = ParagraphStyle(
                'Subtitle',
                parent=styles['Heading2'],
                fontSize=12,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#3498db'),
                spaceBefore=10,
                spaceAfter=6
            )

            # Elementos do PDF
            elements = []

            # Cabeçalho
            elements.append(
                Paragraph("RELATÓRIO DE INSPEÇÃO DE FROTA", title_style))
            elements.append(Paragraph(f"Inspeção #{inspecao['id']} - {inspecao['placa']}",
                                      ParagraphStyle(
                name='Subtitle',
                parent=styles['Normal'],
                fontSize=10,
                alignment=TA_CENTER,
                spaceAfter=16
            )))

            elements.append(HRFlowable(width="100%", thickness=1,
                            spaceAfter=12, color=colors.lightgrey))

            # Seção 1: Informações Básicas
            elements.append(Paragraph("INFORMAÇÕES BÁSICAS", subtitle_style))

            basic_data = [
                ["Placa:", inspecao['placa']],
                ["Veículo:", inspecao['veiculo_modelo']],
                ["Motorista:", inspecao['motorista_nome']],
                ["Data/Hora:",
                    inspecao['data_inspecao'].strftime('%d/%m/%Y %H:%M')],
                ["KM Atual:", str(inspecao['km_atual'])],
                ["Horímetro:", str(inspecao['horimetro'])]
            ]

            basic_table = Table(basic_data, colWidths=[2*inch, 4*inch])
            basic_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (0, -1), 0),
                ('LEFTPADDING', (1, 0), (1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
            ]))

            elements.append(basic_table)
            elements.append(Spacer(1, 0.3*inch))

            # Seção 2: Checklist
            elements.append(Paragraph("CHECKLIST DE INSPEÇÃO", subtitle_style))

            for section_title, items in checklist_items:
                # Título da seção
                elements.append(Paragraph(section_title, styles['Heading3']))
                elements.append(Spacer(1, 0.1*inch))

                # Dados da tabela
                checklist_data = []
                for item_name, item_value in items:
                    status = "Conforme" if item_value == 1 else "Não Conforme" if item_value == 0 else "N/I"
                    checklist_data.append([item_name, status])

                # Criar tabela
                checklist_table = Table(
                    checklist_data, colWidths=[4*inch, 1.5*inch])
                checklist_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ('ALIGN', (1, 0), (1, -1), 'CENTER'),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')),
                    ('TEXTCOLOR', (1, 0), (1, -1),
                        colors.green if item_value == 1 else colors.red if item_value == 0 else colors.grey)
                ]))

                elements.append(checklist_table)
                elements.append(Spacer(1, 0.2*inch))

            # Seção 3: Observações
            if inspecao.get('observacoes'):
                elements.append(Paragraph("OBSERVAÇÕES", subtitle_style))
                elements.append(
                    Paragraph(inspecao['observacoes'], styles['Normal']))
                elements.append(Spacer(1, 0.2*inch))

            # Seção 4: Responsáveis
            elements.append(Paragraph("RESPONSÁVEIS", subtitle_style))

            responsaveis_data = [
                ["Responsável:", inspecao['responsavel_nome']],
                ["Data da Inspeção:", inspecao['data_inspecao'].strftime(
                    '%d/%m/%Y %H:%M')]
            ]

            responsaveis_table = Table(
                responsaveis_data, colWidths=[2*inch, 4*inch])
            responsaveis_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey)
            ]))

            elements.append(responsaveis_table)

            # Rodapé
            elements.append(Spacer(1, 0.4*inch))
            elements.append(HRFlowable(width="100%", thickness=1,
                            spaceBefore=6, spaceAfter=6, color=colors.lightgrey))
            elements.append(Paragraph("Sistema de Gestão de Frota - Linha Viva",
                                      ParagraphStyle(
                                          name='Footer',
                                          parent=styles['Normal'],
                                          fontSize=8,
                                          alignment=TA_CENTER,
                                          textColor=colors.gray
                                      )))
            elements.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                                      ParagraphStyle(
                name='FooterDate',
                parent=styles['Normal'],
                fontSize=8,
                alignment=TA_CENTER,
                textColor=colors.gray
            )))

            # Construir PDF
            doc.build(elements)

            # Retornar resposta
            buffer.seek(0)
            response = make_response(buffer.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = (
                f'attachment; filename='
                f'inspecao_{inspecao["id"]}_{inspecao["placa"]}_'
                f'{datetime.now().strftime("%Y%m%d")}.pdf'
            )

            return response

    except Exception as e:
        current_app.logger.error(f"Erro ao gerar PDF: {str(e)}", exc_info=True)
        flash(f'Erro ao gerar PDF: {str(e)}', 'error')
        return redirect(url_for('main.visualizar_inspecao_frota', id=id))


@main_bp.route('/frota/checar-horimetro')
@login_required
def checar_horimetro_frota():
    try:
        with mysql.connection.cursor() as cur:
            # Buscar todos os veículos com seu último horímetro
            cur.execute("""
                SELECT 
                    v.placa,
                    v.modelo,
                    (SELECT i.horimetro 
                     FROM inspecoes i 
                     WHERE i.placa = v.placa 
                     ORDER BY i.data_inspecao DESC 
                     LIMIT 1) as ultimo_horimetro
                FROM veiculos v
                ORDER BY v.placa
            """)

            veiculos = []
            for row in cur.fetchall():
                placa = row['placa']
                modelo = row['modelo']
                ultimo_horimetro = float(
                    row['ultimo_horimetro']) if row['ultimo_horimetro'] is not None else None

                if ultimo_horimetro is not None:
                    horas_restantes = 300 - ultimo_horimetro
                    proxima_troca = 300  # Valor para próxima troca
                    status = (
                        'danger' if horas_restantes <= 0 else
                        'warning' if horas_restantes <= 50 else
                        'info' if horas_restantes <= 100 else
                        'success'
                    )
                else:
                    horas_restantes = None
                    proxima_troca = None
                    status = 'secondary'

                veiculos.append({
                    'placa': placa,
                    'modelo': modelo,
                    'ultimo_horimetro': ultimo_horimetro,
                    'horas_restantes': horas_restantes,
                    'proxima_troca': proxima_troca,  # Adicionando este campo
                    'status': status
                })

            return render_template('frota/checar_horimetro_frota.html',
                                   veiculos=veiculos)

    except Exception as e:
        flash(f'Erro ao verificar horímetros: {str(e)}', 'error')
        current_app.logger.error(
            f"Erro em checar_horimetro_frota: {str(e)}", exc_info=True)
        return redirect(url_for('main.frota'))
