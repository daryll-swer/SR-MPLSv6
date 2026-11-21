# Build the Internet-Draft with xml2rfc.
#
#   make                 render text and HTML into $(BUILD)/, and refresh the
#                        committed plain-text copy, $(DRAFT).txt
#   make pdf             render PDF (needs xml2rfc[pdf] and its fonts)
#   make submit          write the expanded XML to upload to the datatracker
#   make idnits          check the expanded XML with idnits
#   make check-readable  fail if the committed plain-text copy is out of date
#   make site            assemble the editor's copy for GitHub Pages
#   make clean           remove $(BUILD)/
#
# The revision is taken from the docName attribute in the XML source, so
# outputs are named e.g. build/draft-swer-spring-sr-mplsv6-00.txt.

DRAFT   := draft-swer-spring-sr-mplsv6
REV     := $(shell sed -n 's/.*docName="$(DRAFT)-\([0-9][0-9]\)".*/\1/p' $(DRAFT).xml)
XML2RFC ?= xml2rfc
IDNITS  ?= npx --yes @ietf-tools/idnits@3.3.0
BUILD   ?= build
OUT     := $(BUILD)/$(DRAFT)-$(REV)
SITE    := $(BUILD)/site

ifeq ($(REV),)
$(error could not determine the revision from docName in $(DRAFT).xml)
endif

# Plain-text copy committed to the repository so that the draft can be read on
# GitHub. It is unpaginated, and has no revision in its name so that links to
# it stay stable. FRESH is a new rendering. MASKED is FRESH with the build date
# masked (document date, expiry date, copyright year), because those lines
# change whenever the draft is rendered on a new day.
READABLE := $(DRAFT).txt
FRESH    := $(BUILD)/readable/$(DRAFT).txt
MASKED   := $(BUILD)/readable/$(DRAFT).masked
MONTH    := (January|February|March|April|May|June|July|August|September|October|November|December)
MASK     := sed -E -e 's/[0-9]{1,2} $(MONTH) [0-9]{4}/@DATE@/g' \
                   -e 's/Copyright \(c\) [0-9]{4}/Copyright (c) @YEAR@/' \
                   -e '/@DATE@/s/ +/ /g'

.PHONY: all txt html pdf submit idnits readable check-readable site clean

all: txt html readable

txt: $(OUT).txt
html: $(OUT).html
pdf: $(OUT).pdf
submit: $(OUT).xml
readable: $(READABLE)

$(OUT).txt: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --text --out $@ $<

$(OUT).html: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --html --out $@ $<

$(OUT).pdf: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --pdf --out $@ $<

$(OUT).xml: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --expand --out $@ $<

$(FRESH): $(DRAFT).xml
	@mkdir -p $(@D)
	$(XML2RFC) --text --no-pagination --out $@ $<

$(MASKED): $(FRESH)
	$(MASK) $< > $@

# Replace the committed copy only if more than the build date has changed.
$(READABLE): $(MASKED)
	@if [ -f $@ ] && $(MASK) $@ | cmp -s - $<; then touch $@; \
	else cp $(FRESH) $@ && echo "Updated $@; commit it with the XML."; fi

# Compare with the copy committed at HEAD rather than the working copy, which
# "make" may already have refreshed.
check-readable: $(MASKED)
	@git show HEAD:$(READABLE) | $(MASK) | diff -u - $< || \
	{ echo "$(READABLE) is out of date: run 'make' and commit it." >&2; exit 1; }

# Editor's copy, published to GitHub Pages by CI. The XML source is included
# because the HTML links to it.
site: $(OUT).html $(READABLE)
	rm -rf $(SITE)
	mkdir -p $(SITE)
	cp $(OUT).html $(SITE)/index.html
	cp $(OUT).html $(SITE)/$(DRAFT).html
	cp $(READABLE) $(DRAFT).xml $(SITE)/

idnits: $(OUT).xml
	$(IDNITS) --mode submission --fail-on errors $<

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)
