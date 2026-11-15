# Projeto Final POA Q3/2026: Etapas 2 e 3 (Modelagem Matematica e Resultados)

**Disciplina:** Pesquisa Operacional Aplicada (UFABC, 3o Quadrimestre de 2026)  
**Docente:** Profa. Carolina Correa de Carvalho  
**Grupo 11:** Isabella Paulino, Camille Bevilaqua e Felipe Alves  
**Escopo:** Otimizacao da tomada de decisao de goleiros em cobrancas de penalti via Teoria dos Jogos (Soma Zero 3x3) e Programacao Linear Primal-Dual com dualidade de publico (Treinador de Goleiros + Goleiro).  

---

## 1. Pipeline de Dados e Escopo Empirico (Bronze -> Silver -> Gold)

Os modelos substituem premissas artificiais de salto por coordenadas espaciais observadas de chute e acao do goleiro, processadas em arquitetura Medallion no **Google BigQuery** (`dev-plataforma-geral`, regiao `southamerica-east1`):

| Camada / Tabela | Volume | Transformacao e Regra Aplicada |
|---|---:|---|
| `po_bronze.raw_kaggle_penalties_sofascore` | 16.629 | Ingestao bruta integral do dataset Sofascore (*16k+ Football Penalties GK vs Shooter*), 27 colunas. |
| `po_silver.stg_football_penalties_clean` | 15.726 | Expurgo de 903 cobrancas de handebol (14 equipes) e normalizacao espacial da baliza (`x=0` vs `x=100`). |
| Amostra espacial enriquecida (`has_spatial_coords = TRUE`) | 1.377 | Classificacao completa de `gk_zone` e `shot_zone` em `L/C/R`; `143` defesas + `58` fora/trave (`201` nao-gols = `14.60%`). Pe dominante imputado em 100% (`996` destros, `381` canhotos). |
| `po_gold.mart_payoff_matrices_3x3` | 6 cenarios | Matrizes de payoff 3x3 (`P(Nao-Gol)`), solucoes Primal-Dual (`p*`, `q*`, `V*`, `W*`) e gap `< 1e-9`. |
| `po_gold.mart_sensitivity_theta` | 66 pontos | Curvas parametricas `V*(theta)` nos 6 cenarios para `theta` de `0.0` a `1.0` (passo `0.1`). |
| `po_gold.mart_shooter_scouting` | 10 jogadores | Dossie individual com Empirical Bayes (`alpha=5.0`) para as principais estrelas com `>= 10` lances espaciais. |

---

## 2. Etapa 2: Formulacao Matematica Formal

### 2.1 Conjuntos, Indices e Parametros

- **Conjunto de acoes do Goleiro (linha):** $i \in I = \{L, C, R\}$ (Esquerda, Centro, Direita sob a perspectiva padronizada do batedor).
- **Conjunto de acoes do Batedor (coluna):** $j \in J = \{L, C, R\}$.
- **Matriz de Payoffs do Goleiro ($A = [a_{ij}]$):** probabilidade empirica ou regularizada de o cobrador **nao converter o penalti** (`outcome = 'missed'`, somando defesas e bolas fora/trave) quando o goleiro escolhe a zona $i$ e o batedor chuta na zona $j$:
$$a_{ij} = P(\text{Nao-Gol} \mid \text{Goleiro} = i,\; \text{Batedor} = j) = \frac{m_{ij} + \alpha \cdot a_{ij}^{\text{prior}}}{n_{ij} + \alpha}$$
onde $\alpha = 0$ nos cenarios com alta massa amostral (`C1`, `C2`, `C4`, `C5`, `C6`), $\alpha = 2{,}0$ em `C3_LEFT_FOOT` (encolhimento bayesiano para `C1_GLOBAL` devido a celulas `L_C` e `R_C` com $0$ erros observados) e $\alpha = 5{,}0$ no scouting individual por atleta (encolhimento para o cenario do respectivo pe dominante).

### 2.2 Modelo Primal (Perspectiva do Goleiro: Maximin)

O goleiro escolhe probabilidades mistas $p = (p_L, p_C, p_R)$ para **maximizar o seu pior cenario garantido** $V$ independentemente do canto escolhido pelo batedor:

$$\max_{p_L, p_C, p_R, V} \; V$$
$$\text{sujeito a: } \sum_{i \in \{L,C,R\}} p_i a_{ij} \ge V, \quad \forall j \in \{L, C, R\}$$
$$p_L + p_C + p_R = 1, \qquad p_i \ge 0 \;\; \forall i \in \{L, C, R\}$$

### 2.3 Modelo Dual (Perspectiva do Batedor: Minimax)

O batedor escolhe probabilidades mistas $q = (q_L, q_C, q_R)$ para **minimizar a maxima taxa de nao-gol** $W$ que o goleiro possa atingir:

$$\min_{q_L, q_C, q_R, W} \; W$$
$$\text{sujeito a: } \sum_{j \in \{L,C,R\}} a_{ij} q_j \le W, \quad \forall i \in \{L, C, R\}$$
$$q_L + q_C + q_R = 1, \qquad q_j \ge 0 \;\; \forall j \in \{L, C, R\}$$

Pelo **Teorema da Dualidade Forte** e pelo **Teorema Minimax de Von Neumann**, no otimo global temos $V^* = W^*$ (`duality_gap < 1e-9`).

### 2.4 Analise de Sensibilidade Parametrica Linear $V^*(\theta)$

Para modelar a confianca pratica $\theta \in [0, 1]$ no relatorio de scouting do adversario ($\hat{q}_{\text{emp}}$), restringimos a estrategia do batedor a combinacao convexa $q(\theta) = \theta \hat{q}_{\text{emp}} + (1 - \theta)\tilde{q}$, onde o batedor otimiza apenas a parcela residual $\tilde{q} \in \Delta^2$. Substituindo na funcao de payoff, obtemos uma **matriz efetiva linear** $A(\theta)$:

$$A_{ij}(\theta) = \theta \cdot (A \hat{q}_{\text{emp}})_i + (1 - \theta) \cdot a_{ij}$$

Propriedades matematicas demonstradas e verificadas em teste automatizado (`TC-E3-02A`):
1. **Fronteira $\theta = 0$:** recupera exatamente o Equilibrio de Nash puro $V^*(0) = v^*_{\text{Nash}}$.
2. **Fronteira $\theta = 1$:** equivale a Best Response pura contra o habito historico, $V^*(1) = \max_i (A\hat{q}_{\text{emp}})_i$.
3. **Monotonicidade e Sanduiche de Risco:** $V^*(\theta)$ e nao decrescente e convexa linear por partes em $\theta$, satisfazendo sempre $Fl(p^*(\theta)) \le V^*(\theta) \le EV_{\text{emp}}(p^*(\theta))$, onde $Fl(p) = \min_j (p^\top A)_j$ mede o piso de pior caso caso o batedor percaba a leitura e adapte o chute.
4. **Linearidade para Excel Solver:** como $\theta$ entra linearmente na matriz $A(\theta)$, cada ponto resolve exatamente no suplemento **Simplex LP** do Excel.

---

## 3. Etapa 3: Resultados dos 6 Cenarios e Matrizes 3x3

### 3.1 Quadro Comparativo Geral (Equilibrio de Nash vs Comportamento Empirico)

| Cenario | Amostra (`n`) | Nao-Gol Emp. | `p_emp (L / C / R)` | `p* Nash (L / C / R)` | `q_emp (L / C / R)` | `q* Nash (L / C / R)` | `V* = W*` | Gap |
|---|---:|---:|---|---|---|---|---:|---:|
| `C1_GLOBAL` | 1377 | 14.60% | 26.1% / 33.8% / 40.2% | **28.7% / 38.1% / 33.2%** | 43.0% / 10.9% / 46.1% | 29.6% / 36.5% / 33.9% | **13.94%** | `0.00e+00` |
| `C2_RIGHT_FOOT` | 996 | 15.06% | 27.5% / 32.0% / 40.5% | **33.5% / 34.3% / 32.2%** | 39.9% / 11.6% / 48.5% | 29.6% / 37.7% / 32.8% | **14.37%** | `0.00e+00` |
| `C3_LEFT_FOOT` | 381 | 13.39% | 22.3% / 38.3% / 39.4% | **16.3% / 49.1% / 34.6%** | 51.2% / 8.9% / 39.9% | 27.9% / 36.1% / 36.0% | **12.14%** | `4.16e-17` |
| `C4_CLUTCH` | 616 | 14.77% | 25.8% / 33.8% / 40.4% | **25.2% / 36.9% / 37.8%** | 43.7% / 10.6% / 45.8% | 23.3% / 46.5% / 30.2% | **14.12%** | `2.78e-17` |
| `C5_FORWARDS` | 841 | 15.22% | 27.0% / 31.5% / 41.5% | **25.3% / 43.4% / 31.3%** | 43.0% / 10.7% / 46.3% | 29.6% / 37.0% / 33.4% | **13.10%** | `2.78e-17` |
| `C6_MID_DEF` | 536 | 13.62% | 24.6% / 37.3% / 38.1% | **37.2% / 28.7% / 34.2%** | 42.9% / 11.2% / 45.9% | 29.3% / 36.2% / 34.6% | **15.18%** | `0.00e+00` |

### 3.2 Matrizes de Payoff $A = [a_{ij}]$ (% de Nao-Gol) e Leitura Tatica

| Cenario | Goleiro \\ Chute | Chute L (`a_*,L`) | Chute C (`a_*,C`) | Chute R (`a_*,R`) |
|---|---|---:|---:|---:|
| `C1_GLOBAL` | **Goleiro L** | 37.89% (61/161) | 2.86% (1/35) | 4.91% (8/163) |
|  | **Goleiro C** | 5.05% (10/198) | 30.19% (16/53) | 4.21% (9/214) |
|  | **Goleiro R** | 3.43% (8/233) | 4.84% (3/62) | 32.95% (85/258) |
| `C2_RIGHT_FOOT` | **Goleiro L** | 37.50% (45/120) | 4.00% (1/25) | 5.43% (7/129) |
|  | **Goleiro C** | 1.69% (2/118) | 32.50% (13/40) | 4.97% (8/161) |
|  | **Goleiro R** | 3.77% (6/159) | 5.88% (3/51) | 33.68% (65/193) |
| `C3_LEFT_FOOT` | **Goleiro L** | 38.97% (16/41) | 0.48% (0/10) | 3.05% (1/34) |
|  | **Goleiro C** | 9.88% (8/80) | 24.03% (3/13) | 1.97% (1/53) |
|  | **Goleiro R** | 2.72% (2/74) | 0.74% (0/11) | 30.83% (20/65) |
| `C4_CLUTCH` | **Goleiro L** | 41.18% (28/68) | 6.25% (1/16) | 5.33% (4/75) |
|  | **Goleiro C** | 4.00% (4/100) | 26.09% (6/23) | 3.53% (3/85) |
|  | **Goleiro R** | 5.94% (6/101) | 7.69% (2/26) | 30.33% (37/122) |
| `C5_FORWARDS` | **Goleiro L** | 39.45% (43/109) | 0.00% (0/23) | 4.21% (4/95) |
|  | **Goleiro C** | 3.67% (4/109) | 28.12% (9/32) | 4.84% (6/124) |
|  | **Goleiro R** | 4.86% (7/144) | 2.86% (1/35) | 31.76% (54/170) |
| `C6_MID_DEF` | **Goleiro L** | 34.62% (18/52) | 8.33% (1/12) | 5.88% (4/68) |
|  | **Goleiro C** | 6.74% (6/89) | 33.33% (7/21) | 3.33% (3/90) |
|  | **Goleiro R** | 1.12% (1/89) | 7.41% (2/27) | 35.23% (31/88) |

**Principais achados estatisticos e estrategicos:**
1. **Sub-cobertura do centro e vies real dos batedores (`C1_GLOBAL`):** batedores chutam no centro apenas **10.9%** das vezes (contra **36.5%** do Nash) porque errar no meio acarreta falha de **30.19%** quando o goleiro nao pula. Porem, quando o goleiro salta para os cantos, o chute central converte ~95%-97% (`a_L_C = 2.86%`, `a_R_C = 4.84%`). Para impedir essa exploracao no equilibrio minimax, o goleiro precisa permanecer no **Centro em 38.1%** das cobrancas (acima dos `33.8%` observados).
2. **Inversao Empirica vs. Minimax (`C6_MID_DEF` vs. `C5_FORWARDS`):** atacantes (`C5`) tem taxa empirica maior de nao-gol (`15.22%` vs `13.62%` em `C6`), mas sofrem menos bloqueio quando chutam no centro contra goleiro que salta (`a_L_C = 0.00%`, `a_R_C = 2.86%`), rebaixando o valor garantido Minimax de `C5` para `13.10%`. Ja contra Meio/Defesa (`C6`), o jogo e mais equilibrado e o Nash eleva a protecao garantida para **`15.18%`** (acima do empirico `13.62%`).
3. **Assimetria Destro vs. Canhoto (`C2` vs. `C3`):** destros (`C2`) preferem `R` (`48.5%`, lado oposto/aberto) e equilibram em `33.5% / 34.3% / 32.2%`. Canhotos (`C3`) carregam `51.2%` em `L` (`Opposite`) e forcariam o goleiro a ficar **`49.1%` no Centro** sob Nash puro devido a `a_C_L = 9.88%` e a escassez de erros no centro com salto lateral.
4. **Pressao / Clutch (`C4_CLUTCH`):** em jogos decididos nos 15 minutos finais ou placar apertado (`diff <= 1`), a diagonal esquerda atinge a maior taxa de erro de todo o estudo (**`a_L_L = 41.18%`**).

---

## 4. Curva de Sensibilidade $V^*(\theta)$ e Ponto Critico de Decisao

| Cenario | `V*(0.0)` Nash | Fim da Blindagem Nash | `theta_crit` (1a transicao) | `V*(0.7)` | `V*(1.0)` Best Resp. | Piso `Fl(p*(1.0))` |
|---|---:|---:|---:|---:|---:|---:|
| `C1_GLOBAL` | 13.94% | `theta = 0.6` | `theta = 0.7` | 14.07% | **18.86%** | 2.86% |
| `C2_RIGHT_FOOT` | 14.37% | `theta = 0.6` | `theta = 0.7` | 14.68% | **18.52%** | 3.77% |
| `C3_LEFT_FOOT` | 12.14% | `theta = 0.5` | `theta = 0.6` | 14.99% | **21.21%** | 0.48% |
| `C4_CLUTCH` | 14.12% | `theta = 0.5` | `theta = 0.6` | 16.55% | **21.08%** | 5.33% |
| `C5_FORWARDS` | 13.10% | `theta = 0.6` | `theta = 0.7` | 13.25% | **18.93%** | 0.00% |
| `C6_MID_DEF` | 15.18% | `theta = 0.6` | `theta = 0.7` | 15.36% | **18.49%** | 5.88% |

**Interpretacao para o Treinador de Goleiros:**
- Enquanto a confianca no scouting for moderada (`theta <= 0.5` em Canhotos/Clutch ou `theta <= 0.6` nos demais cenarios), **nao compensa abandonar o Equilibrio de Nash** (`V*(theta) = V*(0)`), pois a perda de piso no pior cenario (`Fl` despencando de `13.94%` para `2.86%` no Global e para `0.00%` contra Atacantes) anula o ganho esperado contra o habito historico.
- Somente quando o dossie do batedor for altamente confiavel (`theta >= 0.7`), a base Simplex muda de vertice via hedges assimetricos (ex.: `C2_RIGHT_FOOT` com `5.9% L / 94.1% R`; `C4_CLUTCH` com `96.1% L / 3.9% R`) e eleva a protecao garantida em `+4,1 p.p.` a `+9,1 p.p.`.

---

## 5. Dossie Scouting dos 10 Batedores de Elite (`mart_shooter_scouting`)

| # | Jogador | Pe | Espacial / Carreira | Chutes `L / C / R` | `Nat / Ctr / Opp` | `p* Nash (L/C/R)` | `V*(0)` | `p*(0.5)` (`theta=0.5`) | `BR (theta=1)` | `EV Best Resp.` |
|---:|---|---|---:|---|---|---|---|---|---:|---:|
| 1 | **Harry Kane** [Luva] | right-foot | 28 / 72 | 11 / 0 / 17 | 11 / 0 / 17 | 23.3 / 26.6 / 50.1 | 12.52% | 23.3 / 26.6 / 50.1 | **R** | **17.47%** |
| 2 | **Kylian Mbappé** [Luva] | right-foot | 19 / 40 | 6 / 3 / 10 | 6 / 3 / 10 | 30.1 / 35.3 / 34.6 | 12.45% | 30.1 / 35.3 / 34.6 | **R** | **17.29%** |
| 3 | **Mohamed Salah** [Luva] | left-foot | 12 / 51 | 7 / 2 / 3 | 3 / 2 / 7 | 18.9 / 40.8 / 40.3 | 10.12% | 89.4 / 10.6 / 0.0 | **L** | **23.56%** |
| 4 | **Bruno Fernandes** [Luva] | right-foot | 10 / 40 | 3 / 0 / 7 | 3 / 0 / 7 | 25.5 / 32.0 / 42.5 | 13.92% | 25.5 / 32.0 / 42.5 | **R** | **19.60%** |
| 5 | **Erling Haaland** [Luva] | left-foot | 10 / 31 | 7 / 0 / 3 | 3 / 0 / 7 | 15.5 / 42.2 / 42.3 | 10.53% | 91.4 / 8.6 / 0.0 | **L** | **26.56%** |
| 6 | **Cole Palmer** [Luva] | left-foot | 10 / 20 | 3 / 1 / 6 | 6 / 1 / 3 | 18.2 / 56.9 / 24.9 | 11.66% | 0.0 / 0.0 / 100.0 | **R** | **26.17%** |
| 7 | **Hakan Çalhanoğlu** | right-foot | 11 / 30 | 4 / 0 / 7 | 4 / 0 / 7 | 39.6 / 31.8 / 28.5 | 13.60% | 11.5 / 0.0 / 88.5 | **R** | **25.26%** |
| 8 | **Mikel Oyarzabal** | left-foot | 11 / 30 | 3 / 3 / 5 | 5 / 3 / 3 | 11.5 / 51.6 / 36.9 | 9.14% | 11.5 / 51.6 / 36.9 | **R** | **10.80%** |
| 9 | **Robert Lewandowski** | right-foot | 11 / 23 | 6 / 0 / 5 | 6 / 0 / 5 | 37.3 / 42.1 / 20.5 | 16.40% | 66.7 / 33.3 / 0.0 | **L** | **30.66%** |
| 10 | **Ante Budimir** | left-foot | 16 / 22 | 9 / 0 / 7 | 7 / 0 / 9 | 12.1 / 54.0 / 33.9 | 13.29% | 12.1 / 54.0 / 33.9 | **L** | **22.76%** |

**Traducao pratica para o Goleiro (Visao de Luva / Vestiario, sem jargao matematico):**
- **Destros de canto cruzado/aberto (`Harry Kane`, `Bruno Fernandes`, `Kylian Mbappe`, `Hakan Calhanoglu`):** concentram `60%` a `70%` dos chutes em `R` (`Opposite`) e raramente usam o centro (`0/28` em Kane, `0/10` em Bruno); comando de luva prioriza **Direita (`R`)** ou roleta ponderada quando o batedor varia.
- **Canhotos de canto aberto (`Mohamed Salah`, `Erling Haaland`):** chutam forte em `L` (`7/12` Salah e `7/10` Haaland); mesmo em confianca intermediaria (`theta = 0.5`), o algoritmo desloca `~90%` para **Esquerda (`L`)**.
- **Canhoto de canto natural (`Cole Palmer`) e especialista imprevisivel (`Mikel Oyarzabal`):** Palmer inverte o padrao dos canhotos (`6/10 Natural = R`, comando **`R`** em `theta=0.5` com `26.17%`), enquanto Oyarzabal (`0/11` erros espaciais, `L/C/R = 3/3/5`) exige **Roleta de Nash** estrita (`V*(0)=9.14%`).

---

## 6. Validacao Cruzada no Excel Solver e Planilha Oficial

1. **Validacao matematica independente ([validacao_excel_solver.xlsx](validacao_excel_solver.xlsx)):**
   - A aba `Modelo_Solver_LP` implementa os 6 cenarios com celulas de matriz base `A`, celula parametrica `B3` (`theta`), vetor linearizado `A_eff(theta)`, celulas variaveis `J6:J8` (`p*`) + **`J11` (`V*` como variavel explicita de decisao)**, restricoes `J9 = SUM(J6:J8) = 1` e `G10:I10 >= J11` (`SUMPRODUCT`), pronta para execucao direta no suplemento **Dados -> Solver -> Simplex LP** sem erro de nao linearidade.
2. **Planilha oficial da disciplina atualizada ([Escolha_Grupos_Seminarios_PO_Grupo11_atualizada.xlsm](Escolha_Grupos_Seminarios_PO_Grupo11_atualizada.xlsm)):**
   - Substitui integralmente o rascunho antigo da aba `Projeto Final Etapa 2 - Modelag` (Linha 3, Grupo 11), alinhando as 7 respostas (`B3` a `H3`) aos dados reais do BigQuery (`15.726` / `1.377`), PL Primal-Dual, Empirical Bayes e sensibilidade `V*(theta)`.

### Textos Consolidados da Aba `Projeto Final Etapa 2 - Modelag` (Linha 3, Colunas B a H)

#### Coluna B - Problema

Situacao a melhorar: alta imprevisibilidade e tomada de decisao intuitiva dos goleiros em cobrancas de penalti no futebol profissional. Na base real tratada de 15.726 penaltis (1.377 com registro espacial simultaneo de chute e salto; taxa observada de nao-gol de 14,60%), os goleiros sofrem penalizacao imediata quando antecipam o canto sem calibracao estocastica (nao-gols caem para 2,86% a 5,05% fora da diagonal).

Decisao a ser tomada: determinar a estrategia mista otima p* = (p_L, p_C, p_R) de escolha de canto do goleiro (Esquerda, Centro, Direita) e seu ajuste parametrico conforme o nivel de confianca theta em [0, 1] no scouting do batedor, atendendo dois perfis de clube: Treinador de Goleiros (visao analitica) e Goleiro (visao enxuta de luva).

#### Coluna C - Modelo

Teoria dos Jogos (Jogo de Soma Zero 3x3 em estrategias mistas: Goleiro x Batedor) resolvida por Programacao Linear (PL) Primal-Dual (Teorema Minimax de Von Neumann), integrada a duas extensoes aplicadas:
1) Suavizacao Bayesiana Empirica (Empirical Bayes shrinkage com alpha = 2,0 no cenario Canhotos e alpha = 5,0 por batedor individual no scouting), evitando probabilidades zero artificiais em celulas esparsas.
2) Analise de Sensibilidade Parametrica linearizada A(theta) = theta*(A*q_emp) + (1 - theta)*A para theta em [0, 1], conectando o Equilibrio de Nash inexploravel (theta = 0) a Best Response de scouting (theta = 1).

#### Coluna D - Justificativa

- Natureza estritamente competitiva (soma zero): cada ponto percentual de taxa de nao-gol conquistado pelo goleiro corresponde exatamente a perda esperada de conversao do batedor.
- Impossibilidade de estrategia pura: como o jogo 3x3 nao possui ponto de sela puro, fixar um lado reduz a protecao para 2,86%-3,43%, enquanto o acerto de canto eleva o nao-gol para 30,19%-37,89%.
- Substituicao de premissas por coordenadas reais: diferentemente de bases pequenas sem direcao do salto, a base Sofascore traz coord. reais de bola e goleiro em 1.377 lances (143 defesas e 58 fora/trave).
- O parametro theta transforma o modelo em ferramenta pratica de vestiario, revelando objetivamente a partir de qual nivel de confianca no dossie vale abandonar a mistura Nash.

#### Coluna E - Representacao do problema

Dados: pipeline Medallion no Google BigQuery (16.629 brutas Kaggle -> expurgo de 903 linhas de handebol -> 15.726 penaltis de futebol -> 1.377 cobrancas espaciais normalizadas por baliza x=0/x=100, sendo 996 destros e 381 canhotos).

Conjuntos: I = J = {L, C, R} (Esquerda, Centro, Direita sob visao do batedor).
Parametros: matriz A = [a_ij], com a_ij = P(Nao-Gol | Goleiro i, Batedor j); habito empirico q_emp; e matriz parametrica A_ij(theta) = theta*(A*q_emp)_i + (1-theta)*A_ij.
Variaveis de decisao: p_i >= 0 (Goleiro), q_tilde_j >= 0 (Batedor restrito), V (valor Primal) e W (valor Dual).

PL Primal (Goleiro Maximin): max V sujeito a Sum_i p_i * A_ij(theta) >= V (para todo j em {L,C,R}), Sum_i p_i = 1, p_i >= 0.
PL Dual (Batedor Minimax): min W sujeito a Sum_j A_ij(theta) * q_tilde_j <= W (para todo i em {L,C,R}), Sum_j q_tilde_j = 1, q_tilde_j >= 0.

#### Coluna F - Limitacoes e premissas

- Amostra espacial parcial: das 15.726 cobrancas de futebol, 1.377 (8,8%) possuem coordenadas completas de chute e salto; nos recortes individuais (n = 10 a 28 espaciais) e canhotos (n = 381), a regularizacao Bayesiana Empirica reduz variancia extrema.
- Discretizacao horizontal em 3 zonas (L, C, R): nao separa altura do chute (rasteiro vs angulo) nem potencia da batida.
- Agrupamento do evento Nao-Gol: combina defesas diretas (143) e erros fora/trave (58) em 201 falhas totais por representarem o mesmo ganho de placar para o clube defensor.
- Racionalidade idealizada: o equilibrio base (theta = 0) pressupoe adversario capaz de detectar e explorar desvios; por isso a analise de sensibilidade theta quantifica exatamente o risco de pior caso antes da decisao.

#### Coluna G - Resultados esperados

- Cenario Global (C1, n=1.377): estrategia otima do goleiro p* = (28,7% L, 38,1% C, 33,2% R), corrigindo a sub-cobertura do centro observada nos dados (33,8% emp.), garantindo V*(0) = 13,94% com gap Primal-Dual = 0,00e+00.
- 6 Cenarios modelados: Destros V*=14,37%; Canhotos EB V*=12,14%; Clutch V*=14,12%; Atacantes V*=13,10%; Meio/Defensores V*=15,18% (superando a taxa empirica de 13,62%).
- Curva de sensibilidade (66 pontos, theta 0 a 1): revela zona de blindagem ate theta_crit (0,5 a 0,7), a partir da qual V*(theta) sobe ate 18,86% (Global), 21,21% (Canhotos) e 18,49% (Meio/Def.).
- Dossies de 10 estrelas (Harry Kane, Kylian Mbappé, Mohamed Salah, Bruno Fernandes, Erling Haaland, Cole Palmer + Hakan Çalhanoğlu, Mikel Oyarzabal, Robert Lewandowski, Ante Budimir) com cartoes visuais e indicadores de aderencia real x Nash.

#### Coluna H - Aplicacao do modelo

Engenharia e Cloud: Python 3.12 + SQL no Google BigQuery (dev-plataforma-geral, southamerica-east1) nas camadas Bronze, Silver e Gold, governadas por suíte de testes automatizados (Test Switch --stage/--mode).
Modelagem e Validacao: solver exato de vertices Simplex (lp_nash_solver.py) e sensibilidade/scouting (sensitivity_and_scouting.py) com validacao cruzada no suplemento Excel Solver (Simplex LP) via docs/validacao_excel_solver.xlsx (gap < 1e-9 em todos os 66 pontos).
Entrega Aplicada: dados Gold exportados em JSON (po_penalties_mart.json) para alimentar o Portfolio Web interativo com visao tecnica (Treinador), visao enxuta de luva (Goleiro) e Simulador Ao Vivo na apresentacao final (26/11).

---

## 7. Roteiro para a Mentoria da Semana 10 (19/11, 16h30 - 16h45, Grupo 11)

- **Sala confirmada na aba `Semana 10 - 1911 Reunião com ca` (Linha 11):** horario `16h30 - 16h45`, Grupo `11`, link `https://conferenciaweb.rnp.br/sala/carolina-81` (`15 minutos`).
- **Roteiro sugerido (15 min):**
  1. **(0-3 min) Problema e Evolucao da Base:** mostrar a evolucao da amostra inicial de 136 lances sem direcao de salto para o pipeline BigQuery com **15.726 penaltis reais** e **1.377 cobrancas com coordenadas simultaneas de chute e goleiro**.
  2. **(3-7 min) Modelagem PL Primal-Dual + Excel Solver:** apresentar a formulacao Primal/Dual, gap `0,00e+00`, suavizacao Bayesiana Empirica (`C3_LEFT_FOOT`) e abrir a aba `Modelo_Solver_LP` no Excel Solver.
  3. **(7-12 min) Resultados e Sensibilidade `V*(theta)`:** destacar os 6 cenarios, a inversao empirico vs minimax em `C6_MID_DEF` (`15,18%`), a sub-cobertura do centro e o ponto critico `theta_crit` (`0,5` a `0,7`).
  4. **(12-15 min) Validacao de Escopo das Etapas 4 e 5:** confirmar com a Profa. Carolina o formato do **Portfolio Web Dual-Persona** (Treinador Tecnico vs Cartao/Roleta do Goleiro) e do **Jogo Ao Vivo em sala (26/11)**.
