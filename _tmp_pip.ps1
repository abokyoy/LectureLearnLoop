$env:HTTP_PROXY='http://127.0.0.1:10808'
$env:HTTPS_PROXY='http://127.0.0.1:10808'
$env:NO_PROXY='localhost,127.0.0.1'
python -m pip install trafilatura markdownify mammoth --quiet 2> e:\LLM\LectureLearnLoop\_pip_err.txt
"pip exit: $LASTEXITCODE" | Out-File e:\LLM\LectureLearnLoop\_pip_res.txt -Encoding utf8
python -c "import trafilatura, markdownify, mammoth; print('IMPORT-OK', trafilatura.__version__, mammoth.__version__)" 2>> e:\LLM\LectureLearnLoop\_pip_err.txt
"import exit: $LASTEXITCODE" | Out-File e:\LLM\LectureLearnLoop\_pip_res.txt -Append -Encoding utf8
