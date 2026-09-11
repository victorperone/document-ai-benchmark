Quero fazer uma revisão exclusivamente documental do código Python do projeto.

Crie a branch:

`docs/python-docstrings`

a partir de:

`server/windows-native`

Objetivo: melhorar documentação interna do código sem alterar comportamento.

Escopo permitido:

* adicionar docstrings ausentes em módulos, classes, funções e métodos relevantes;
* revisar docstrings existentes que estejam incompletas, incorretas ou desatualizadas;
* padronizar docstrings para um formato consistente;
* documentar parâmetros, retornos, exceções e efeitos colaterais quando isso realmente ajudar;
* adicionar comentários apenas para explicar decisões técnicas, invariantes, workarounds ou comportamento não óbvio.

Restrições obrigatórias:

* não alterar lógica;
* não refatorar código;
* não alterar assinaturas de funções ou métodos;
* não renomear variáveis, classes, funções ou módulos;
* não reorganizar imports;
* não executar autofix;
* não aplicar formatter global;
* não alterar profiles, CLI, configuração, artefatos ou comportamento dos parsers;
* não remover código;
* não modificar testes;
* não alterar strings que sejam usadas programaticamente;
* não adicionar comentários triviais que apenas repitam o código.

Antes de editar uma docstring existente, verifique se ela pode ser acessada programaticamente por `__doc__`, introspecção, geração de CLI ou documentação automática.

Use um padrão de docstring consistente em todo o código Python. Prefiro docstrings claras e objetivas, com seções como `Args`, `Returns` e `Raises` apenas quando forem úteis.

Ao final:

1. execute a suíte de testes existente;
2. confirme que nenhum arquivo funcional foi alterado além de docstrings/comentários;
3. apresente a lista de arquivos modificados;
4. informe quantas docstrings foram adicionadas, atualizadas e removidas;
5. destaque qualquer trecho cuja documentação não pôde ser escrita com segurança por comportamento pouco claro, sem tentar refatorá-lo.

Não faça nenhuma alteração funcional nesta branch.
