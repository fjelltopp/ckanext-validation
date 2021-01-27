this.ckan.module('validation-report', function (jQuery) {
  return {
    options: {
      report: null
    },
    initialize: function() {
      console.log(this.options.report)
      goodtablesUI.render(
        goodtablesUI.Report,
        {report: this.options.report},
        this.el[0]
      )
    }
  }
});
