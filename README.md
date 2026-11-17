# 🌱 EcoAlerta

### Sistema de gerenciamento de ocorrências ambientais

O **EcoAlerta** é um sistema desenvolvido como projeto acadêmico da disciplina de Projeto de Desenvolvimento de Sistemas II, do curso de Sistemas de Informação da Universidade Paulista (UNIP).

A aplicação tem como finalidade auxiliar no registro, gerenciamento e acompanhamento de ocorrências ambientais, contribuindo para a organização das informações e o controle das evidências relacionadas aos registros.

## 🎯 Objetivo do projeto

Desenvolver uma aplicação desktop que permita cadastrar, consultar e gerenciar ocorrências ambientais de maneira organizada, oferecendo recursos para diferentes níveis de acesso e controle das informações.

## ⚙️ Funcionalidades

- **Login:** autenticação de usuários no sistema.
- **Recuperação de senha:** redefinição de senha por meio de código temporário.
- **Gerenciamento de usuários:** cadastro de usuários com perfis de Técnico e Coordenador.
- **Cadastro de ocorrências:** registro de ocorrências ambientais, como desmatamento, queimadas e descarte irregular de lixo.
- **Consulta e gerenciamento:** pesquisa, filtragem, edição e exclusão de ocorrências conforme as permissões de acesso.
- **Evidências:** inclusão e visualização de arquivos de imagem relacionados às ocorrências.
- **Integridade das evidências:** recursos de verificação da integridade dos arquivos.
- **Histórico de atividades:** registro das ações realizadas no sistema.
- **Importação e exportação:** recursos para transferência de dados entre instalações do sistema.

## 💻 Tecnologias utilizadas

- Python
- Tkinter – construção da interface gráfica.
- Pillow – processamento de imagens.
- Cryptography – recursos de criptografia e proteção de informações.

## 📂 Estrutura do projeto

```text
EcoAlerta/
│
├── ecoalerta.py
├── requirements.txt
├── README.md
│
└── imagens/
    └── telas do sistema
```

## 🚀 Instalação e execução

### 1. Pré-requisitos

- Python 3 instalado.
- Git (opcional, para clonar o repositório).

### 2. Clonar o repositório

```bash
git clone https://github.com/ivanmendes28/Ecoalerta
```

### 3. Acessar a pasta do projeto

```bash
cd EcoAlerta
```

### 4. Instalar as dependências

```bash
pip install -r requirements.txt
```

### 5. Executar o sistema

```bash
python ecoalerta.py
```

## 🖥️ Telas do sistema

As imagens das principais telas da aplicação serão apresentadas nesta seção.

<img width="1317" height="892" alt="image" src="https://github.com/user-attachments/assets/8c185df8-ef6d-4c01-aae2-e3f1862a0bdf" />
<img width="1316" height="887" alt="image" src="https://github.com/user-attachments/assets/9f4d3725-a659-4fcb-ad93-eb9590cd41d0" />


## 👥 Integrantes do grupo

Projeto desenvolvido coletivamente pelos alunos:

Alexandry Ravara Vanin - R4536B1 - S.I - 1º Semestre. | 
Aline Cirino - H003FJ9 - S.I - 1º Semestre. | 
Gustavo Santana Cardoso - R444384 - S.I - 1º Semestre. | 
Ivan Mendes - H9983F6 - S.I - 1º Semestre. | 
Larissa Barbosa da Silva - R445542  - S.I - 1º Semestre.

## 🎓 Instituição de ensino

**Universidade Paulista – UNIP**

**Curso:** Sistemas de Informação

**Disciplina:** Projeto de Desenvolvimento de Sistemas II

**Professor:** Marcus Leite

---

*Projeto acadêmico desenvolvido com o objetivo de aplicar conhecimentos de programação Python e desenvolvimento de interfaces gráficas com Tkinter.*
