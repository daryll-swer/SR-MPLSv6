# Build the Internet-Draft with xml2rfc.
#
#   make          render text and HTML into $(BUILD)/
#   make pdf      render PDF (needs xml2rfc[pdf] and its fonts)
#   make submit   write the expanded XML to upload to the datatracker
#   make idnits   check the expanded XML with idnits
#   make clean    remove $(BUILD)/
#
# The revision is taken from the docName attribute in the XML source, so
# outputs are named e.g. build/draft-swer-spring-sr-mplsv6-00.txt.

DRAFT   := draft-swer-spring-sr-mplsv6
REV     := $(shell sed -n 's/.*docName="$(DRAFT)-\([0-9][0-9]\)".*/\1/p' $(DRAFT).xml)
XML2RFC ?= xml2rfc
IDNITS  ?= npx --yes @ietf-tools/idnits@3.3.0
BUILD   ?= build
OUT     := $(BUILD)/$(DRAFT)-$(REV)

ifeq ($(REV),)
$(error could not determine the revision from docName in $(DRAFT).xml)
endif

.PHONY: all txt html pdf submit idnits clean

all: txt html

txt: $(OUT).txt
html: $(OUT).html
pdf: $(OUT).pdf
submit: $(OUT).xml

$(OUT).txt: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --text --out $@ $<

$(OUT).html: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --html --out $@ $<

$(OUT).pdf: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --pdf --out $@ $<

$(OUT).xml: $(DRAFT).xml | $(BUILD)
	$(XML2RFC) --expand --out $@ $<

idnits: $(OUT).xml
	$(IDNITS) --mode submission --fail-on errors $<

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)
