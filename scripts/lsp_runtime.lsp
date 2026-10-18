;;; ---------------------------------------------------------------------------
;;; detail-to-lsp runtime  (version 1.1 - adds HATCH)
;;; Data-driven drawing engine. Each generated detail supplies a quoted record
;;; list; this runtime turns records into entities. The runtime is identical in
;;; every generated file, so it is verified once (lisp_sim.py) and reused.
;;;
;;; Record formats (all coordinates relative to the picked insertion point):
;;;   ("LAYER"    name color lweight ltype)
;;;   ("STYLE"    name font)
;;;   ("DIMSTYLE" name ((var . value) ...))
;;;   ("LINE"     layer (x y) (x y))
;;;   ("PL"       layer flags ((x y bulge) ...) [width])  flags: 1 closed, 128 plinegen
;;;   ("CIRCLE"   layer (x y) r)
;;;   ("ARC"      layer (x y) r a0 a1)             radians, CCW from a0 to a1
;;;   ("TEXT"     layer style (x y) height rot just "string")
;;;   ("LEADER"   layer dimstyle arrow spline ((x y) ...))  first point = arrow
;;;   ("DIM"      layer dimstyle kind (x y) (x y) (x y) rot override oblique)
;;;               kind "ROT" (rotated/linear) or "ALI" (aligned); override and
;;;               oblique may be nil
;;;   ("SOLID"    layer (x y) (x y) (x y) (x y))
;;;   ("HATCH"    layer pattern scale angle (loop ...))
;;;               loop = ((x y bulge) ...), first loop outer, others islands;
;;;               predefined pattern from acad.pat, angle in radians,
;;;               non-associative (temporary boundaries are deleted)
;;; ---------------------------------------------------------------------------

(vl-load-com)

(defun dtl:tp (p)
  (list (+ (car *dtl-bp*) (car p))
        (+ (cadr *dtl-bp*) (cadr p))
        (caddr *dtl-bp*))
)

(defun dtl:warn (msg)
  (setq *dtl-warn* (cons msg *dtl-warn*))
)

;;; ---------- table records ----------
(defun dtl:ltype (name / lts)
  (cond
    ((or (null name) (= (strcase name) "CONTINUOUS")) "Continuous")
    ((tblsearch "LTYPE" name) name)
    (T
      (setq lts (vla-get-Linetypes *dtl-doc*))
      (vl-catch-all-apply 'vla-load (list lts name "acad.lin"))
      (if (not (tblsearch "LTYPE" name))
        (vl-catch-all-apply 'vla-load (list lts name "acadiso.lin"))
      )
      (if (tblsearch "LTYPE" name)
        name
        (progn (dtl:warn (strcat "Linetype " name " not found; used Continuous")) "Continuous")
      )
    )
  )
)

(defun dtl:layer (name color lw ltype)
  (if (tblsearch "LAYER" name)
    T
    (entmake
      (list '(0 . "LAYER")
            '(100 . "AcDbSymbolTableRecord")
            '(100 . "AcDbLayerTableRecord")
            (cons 2 name)
            '(70 . 0)
            (cons 62 color)
            (cons 6 (dtl:ltype ltype))
            (cons 370 lw)))
  )
)

(defun dtl:style (name font)
  (if (tblsearch "STYLE" name)
    T
    (entmake
      (list '(0 . "STYLE")
            '(100 . "AcDbSymbolTableRecord")
            '(100 . "AcDbTextStyleTableRecord")
            (cons 2 name)
            '(70 . 0)
            '(40 . 0.0)
            '(41 . 1.0)
            '(50 . 0.0)
            '(71 . 0)
            '(42 . 1.0)
            (cons 3 font)
            '(4 . "")))
  )
)

;;; Sets dimension variables, copies them into a named style, makes it active.
(defun dtl:dimstyle (name vars / dss ds r)
  (foreach v vars
    (setq r (vl-catch-all-apply 'setvar (list (car v) (cdr v))))
    (if (vl-catch-all-error-p r)
      (dtl:warn (strcat "setvar " (car v) " failed: " (vl-catch-all-error-message r)))
    )
  )
  (setq dss (vla-get-DimStyles *dtl-doc*))
  (setq ds (if (tblsearch "DIMSTYLE" name) (vla-Item dss name) (vla-Add dss name)))
  (vla-CopyFrom ds *dtl-doc*)
  (vla-put-ActiveDimStyle *dtl-doc* ds)
  ds
)

;;; ---------- entities ----------
(defun dtl:line (lay p1 p2)
  (entmake (list '(0 . "LINE") (cons 8 lay)
                 (cons 10 (dtl:tp p1)) (cons 11 (dtl:tp p2))))
)

(defun dtl:pl (lay flags verts width / q out)
  (foreach v verts
    (setq q   (dtl:tp v)
          out (cons (cons 42 (caddr v)) (cons (list 10 (car q) (cadr q)) out)))
  )
  (entmake
    (append
      (list '(0 . "LWPOLYLINE")
            '(100 . "AcDbEntity")
            (cons 8 lay)
            '(100 . "AcDbPolyline")
            (cons 90 (length verts))
            (cons 70 flags)
            (cons 38 (caddr *dtl-bp*)))
      (if width (list (cons 43 width)))
      (reverse out)))
)

(defun dtl:circle (lay c r)
  (entmake (list '(0 . "CIRCLE") (cons 8 lay) (cons 10 (dtl:tp c)) (cons 40 r)))
)

(defun dtl:arc (lay c r a0 a1)
  (entmake (list '(0 . "ARC") (cons 8 lay) (cons 10 (dtl:tp c)) (cons 40 r)
                 (cons 50 a0) (cons 51 a1)))
)

(defun dtl:justify (j)
  (cond ((= j "L") '(0 0))  ((= j "C") '(1 0))  ((= j "R") '(2 0))  ((= j "M") '(4 0))
        ((= j "BL") '(0 1)) ((= j "BC") '(1 1)) ((= j "BR") '(2 1))
        ((= j "ML") '(0 2)) ((= j "MC") '(1 2)) ((= j "MR") '(2 2))
        ((= j "TL") '(0 3)) ((= j "TC") '(1 3)) ((= j "TR") '(2 3))
        (T '(0 0)))
)

(defun dtl:text (lay sty p h rot j str / q jj)
  (setq q (dtl:tp p) jj (dtl:justify j))
  (entmake
    (list '(0 . "TEXT")
          (cons 8 lay)
          (cons 7 sty)
          (cons 10 q)
          (cons 11 q)
          (cons 40 h)
          (cons 1 str)
          (cons 50 rot)
          '(41 . 1.0)
          (cons 72 (car jj))
          (cons 73 (cadr jj))))
)

;;; Annotation-free LEADER; falls back to a polyline if entmake refuses it.
(defun dtl:leader (lay ds arrow spline pts / e)
  (setq e
    (entmake
      (append
        (list '(0 . "LEADER")
              '(100 . "AcDbEntity")
              (cons 8 lay)
              '(100 . "AcDbLeader")
              (cons 3 ds)
              (cons 71 arrow)
              (cons 72 spline)
              '(73 . 3)
              '(74 . 0)
              '(75 . 0)
              '(40 . 0.0)
              '(41 . 0.0)
              (cons 76 (length pts)))
        (mapcar '(lambda (p) (cons 10 (dtl:tp p))) pts))))
  (if (null e)
    (progn
      (dtl:warn "LEADER entmake failed; drew polyline instead")
      (setq e (dtl:pl lay 0 (mapcar '(lambda (p) (list (car p) (cadr p) 0.0)) pts) nil))
    )
  )
  e
)

(defun dtl:solid (lay p1 p2 p3 p4)
  (entmake (list '(0 . "SOLID") (cons 8 lay)
                 (cons 10 (dtl:tp p1)) (cons 11 (dtl:tp p2))
                 (cons 12 (dtl:tp p3)) (cons 13 (dtl:tp p4))))
)

;;; Rotated ("ROT") or aligned ("ALI") dimension through ActiveX.
(defun dtl:dim (lay ds kind p1 p2 dl rot ovr obl / o e ed r)
  (setq r
    (vl-catch-all-apply
      (if (= kind "ALI") 'vla-AddDimAligned 'vla-AddDimRotated)
      (if (= kind "ALI")
        (list *dtl-ms* (vlax-3d-point (dtl:tp p1)) (vlax-3d-point (dtl:tp p2))
              (vlax-3d-point (dtl:tp dl)))
        (list *dtl-ms* (vlax-3d-point (dtl:tp p1)) (vlax-3d-point (dtl:tp p2))
              (vlax-3d-point (dtl:tp dl)) rot))))
  (if (vl-catch-all-error-p r)
    (progn (dtl:warn (strcat "DIM failed: " (vl-catch-all-error-message r))) nil)
    (progn
      (setq o r)
      (vla-put-Layer o lay)
      (vl-catch-all-apply 'vla-put-StyleName (list o ds))
      (if ovr (vla-put-TextOverride o ovr))
      (setq e (vlax-vla-object->ename o))
      (if obl
        (progn
          (setq ed (entget e))
          (if (assoc 52 ed)
            (progn (entmod (subst (cons 52 obl) (assoc 52 ed) ed)) (entupd e))
            (command "_.DIMEDIT" "_O" e "" (angtos obl 0 4))
          )
        )
      )
      e
    )
  )
)

;;; Non-associative predefined-pattern hatch through ActiveX. Boundaries are
;;; temporary closed polylines on the hatch layer, removed after Evaluate.
(defun dtl:hatch-arr (o)
  (vlax-make-variant
    (vlax-safearray-fill (vlax-make-safearray vlax-vbObject '(0 . 0)) (list o)))
)

(defun dtl:hatch-make (lay pat scl ang objs / h)
  (setq h (vla-AddHatch *dtl-ms* 1 pat :vlax-false))
  (vla-put-Layer h lay)
  (if (/= (strcase pat) "SOLID")
    (progn (vla-put-PatternScale h scl) (vla-put-PatternAngle h ang))
  )
  (vla-AppendOuterLoop h (dtl:hatch-arr (car objs)))
  (foreach o (cdr objs) (vla-AppendInnerLoop h (dtl:hatch-arr o)))
  (vla-Evaluate h)
  h
)

(defun dtl:hatch (lay pat scl ang loops / objs r)
  (setq objs
    (mapcar '(lambda (lp) (if (dtl:pl lay 1 lp nil) (vlax-ename->vla-object (entlast))))
            loops))
  (if (member nil objs)
    (setq r nil)
    (setq r (vl-catch-all-apply 'dtl:hatch-make (list lay pat scl ang objs)))
  )
  (foreach o objs (if o (vl-catch-all-apply 'vla-Delete (list o))))
  (cond
    ((null r) (dtl:warn (strcat "HATCH " pat ": boundary failed")) nil)
    ((vl-catch-all-error-p r)
      (dtl:warn (strcat "HATCH " pat " failed: " (vl-catch-all-error-message r))) nil)
    (T r)
  )
)

;;; ---------- dispatcher ----------
(defun dtl:do (r / k)
  (setq k (car r))
  (cond
    ((= k "LAYER")    (dtl:layer (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r)))
    ((= k "STYLE")    (dtl:style (nth 1 r) (nth 2 r)))
    ((= k "DIMSTYLE") (dtl:dimstyle (nth 1 r) (nth 2 r)))
    ((= k "LINE")     (dtl:line (nth 1 r) (nth 2 r) (nth 3 r)))
    ((= k "PL")       (dtl:pl (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r)))
    ((= k "CIRCLE")   (dtl:circle (nth 1 r) (nth 2 r) (nth 3 r)))
    ((= k "ARC")      (dtl:arc (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r) (nth 5 r)))
    ((= k "TEXT")     (dtl:text (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r) (nth 5 r) (nth 6 r) (nth 7 r)))
    ((= k "LEADER")   (dtl:leader (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r) (nth 5 r)))
    ((= k "DIM")      (dtl:dim (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r) (nth 5 r) (nth 6 r)
                               (nth 7 r) (nth 8 r) (nth 9 r)))
    ((= k "SOLID")    (dtl:solid (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r) (nth 5 r)))
    ((= k "HATCH")    (dtl:hatch (nth 1 r) (nth 2 r) (nth 3 r) (nth 4 r) (nth 5 r)))
    (T (dtl:warn (strcat "Unknown record type " k)) nil)
  )
)

;;; ---------- driver ----------
(defun dtl:run (title data / *error* olddim oldcmd ok bad)
  (defun *error* (msg)
    (if olddim (vl-catch-all-apply 'vla-put-ActiveDimStyle (list *dtl-doc* olddim)))
    (if *dtl-doc* (vla-EndUndoMark *dtl-doc*))
    (if oldcmd (setvar "CMDECHO" oldcmd))
    (if (and msg (not (wcmatch (strcase msg) "*CANCEL*,*QUIT*,*EXIT*")))
      (princ (strcat "\n" title " error: " msg))
    )
    (princ)
  )
  (setq *dtl-doc* (vla-get-ActiveDocument (vlax-get-acad-object))
        *dtl-ms*  (vla-get-ModelSpace *dtl-doc*)
        *dtl-warn* nil
        ok 0
        bad 0)
  (setq *dtl-bp* (getpoint (strcat "\n" title " insertion point <0,0>: ")))
  (setq *dtl-bp* (if *dtl-bp* (trans *dtl-bp* 1 0) '(0.0 0.0 0.0)))
  (if (null (caddr *dtl-bp*)) (setq *dtl-bp* (list (car *dtl-bp*) (cadr *dtl-bp*) 0.0)))
  (setq oldcmd (getvar "CMDECHO")
        olddim (vla-get-ActiveDimStyle *dtl-doc*))
  (setvar "CMDECHO" 0)
  (vla-StartUndoMark *dtl-doc*)
  (foreach r data
    (if (dtl:do r)
      (setq ok (1+ ok))
      (progn (setq bad (1+ bad)) (dtl:warn (strcat "Record failed: " (car r))))
    )
  )
  (vl-catch-all-apply 'vla-put-ActiveDimStyle (list *dtl-doc* olddim))
  (setq olddim nil)
  (vla-EndUndoMark *dtl-doc*)
  (setvar "CMDECHO" oldcmd)
  (princ (strcat "\n" title ": " (itoa ok) " records OK, " (itoa bad) " failed."))
  (foreach w (reverse *dtl-warn*) (princ (strcat "\n  - " w)))
  (princ)
)
