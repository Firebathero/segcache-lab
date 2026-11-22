# Papers

PDFs are not committed. Fetch into `papers/dl/` (gitignored) and check the hash.

| key | title | venue | source | sha256 |
|---|---|---|---|---|
| segcache | Segcache: a memory-efficient and scalable in-memory key-value cache for small objects. Juncheng Yang, Yao Yue, K. V. Rashmi. | NSDI '21 | https://www.usenix.org/system/files/nsdi21-yang.pdf | `f0784f1a57b36f0a08ccae0d009c117d8c509614167d97d71797c42e51c92faa` |

Citations in this repository use PDF page numbers of that file (the first page
is the USENIX cover), plus the section number.

## Claims this repository checks

| claim | where | checked in |
|---|---|---|
| Segcache stores 5 bytes of metadata with each object: 8-bit key size, 24-bit value size, 8-bit flag | §3.4, PDF p. 7 | notes/stop-1-layout.md, experiment 01 |
| The 5 bytes exclude shared metadata and the 1-byte frequency counter, which lives in the hash table | §3.4 footnote 4, PDF p. 7 | notes/stop-1-layout.md |
| A 91% reduction compared to Memcached | §3.4, PDF p. 7; introduction, PDF p. 3 | experiment 01 |
| Memcached stores 56 bytes of metadata with each object | §2.2 and footnote 3, PDF p. 4 | notes/stop-1-layout.md |
